
"""
Semantic Release Dagger Module

This Dagger module extends the functionality of the [semantic-release](https://github.com/semantic-release/semantic-release) 
project, providing a containerized and declarative pipeline for fully automated software release workflows. 
Built with [Dagger](https://dagger.io/), this module enables advanced CI/CD customization and composability 
while preserving the core principles of semantic versioning and automated changelog generation.

Features:
- Encapsulates semantic-release as a Dagger pipeline step
- Supports custom plugin injection and configuration
- Optimized for portability and reproducibility across CI environments
- Easily integrable with larger Dagger-based CI/CD pipelines

Attribution:
This module builds on the foundation provided by the [semantic-release](https://github.com/semantic-release/semantic-release) 
project, maintained by its contributors. All semantic-release core functionalities remain under their original 
[license and guidelines](https://github.com/semantic-release/semantic-release/blob/master/LICENSE).
"""

import json
from typing import Annotated
from enum import Enum
from dagger import Container, dag, Directory, Doc, function, object_type, Secret, DefaultPath, enum_type, QueryError
from .releaserc import ReleaseRC


@enum_type
class CiProvider(Enum):
    NONE = "none"
    UNKNOWN = "unknown"
    GITHUB = "github"

SEMANTIC_RELEASE_IMAGE = f"ghcr.io/bcit-ltc/semantic-release:latest"
NEXT_RELEASE_FILE = "next-release.txt"
LAST_RELEASE_FILE = "last-release.txt"
APP_DIR = "/app"

@object_type
class SemanticRelease:
    """
    This class encapsulates the functionality of semantic-release, providing a Dagger-based interface
    for automating software release workflows. It allows users to configure and run semantic-release
    in various environments, including CI/CD pipelines and local development setups.
    The class supports custom plugin injection, configuration, and environment detection, enabling
    seamless integration with existing workflows.
    Attributes:
        github_token (str): GitHub token for authentication in CI/CD environments.
        username (str): GitHub username for commit authoring.
        repository_url (str): URL of the GitHub repository.
        dry_run (bool): Flag to indicate if the release should be a dry run.
        debug (bool): Flag to enable debug mode.
        ci (bool): Flag to indicate if running in a CI environment.
        ci_provider (CiProvider): The CI provider being used (e.g., GitHub).
    """
    github_token: str | None
    releaserc = ReleaseRC()
    branch = "main"

    @function
    async def semanticrelease(self,
            source: Annotated[Directory, Doc("Source directory"), DefaultPath(".")], # source directory
            github_token: Annotated[Secret, Doc("Github Token")] | None,
            username: Annotated[str, Doc("Github Username")] = "local",  # GitHub username
            repository_url: Annotated[str, Doc("Repository URL")] = "", # Repository URL
            dry_run: Annotated[bool, Doc("Dry run mode")] = False, # dry run mode, ignored in local mode(defaults True)
            debug: Annotated[bool, Doc("Debug mode")] = False, # debug mode, ignored in local mode(defaults True)
            ci: Annotated[bool, Doc("CI mode")] = True, # CI mode defaults to true, ignored in local mode(defaults False)
            ) -> str:
        """
        Run semantic-release to analyze commits and determine the next version.
        Returns a JSON string with the last and next release versions.
        """
        # Set instance variables for release config
        self.github_token = github_token
        self.username = username
        self.repository_url = repository_url
        self.dry_run = dry_run
        self.debug = debug
        self.ci = ci

        # Determine the CI provider based on whether the GitHub token is set
        if github_token is not None:
            print("GITHUB_TOKEN detected")
            print("Running in GitHub Actions")
            self.ci_provider = CiProvider.GITHUB
        else:
            print("Running locally, Semantic Release dry run mode with commit analyzer")
            self.ci_provider = CiProvider.NONE

        # Configure semantic-release settings (e.g. CI mode, debug, plugins)
        self._configure_release_params()
        print(f"Configured release parameters: {self.releaserc.to_string()}")

        # Prepare a container environment with dependencies for running semantic-release
        container = await self._prepare_semantic_release_container(source)

        # Run the semantic-release command inside the container depending on execution context
        if self.ci_provider == CiProvider.GITHUB:
            print("Running in GitHub Actions")
            container = await self._github_actions_runner(container)
        else:
            print("Running locally")
            container = await self._local_runner(container)
        
        # Attempt to read the last release version from the output directory
        try:
            output_directory = container.directory(APP_DIR)
            last_release_file = output_directory.file(LAST_RELEASE_FILE)
            last_version = (await last_release_file.contents()).strip()
            print(f"Last release version: {last_version}")
        except QueryError as e:
            print(f"Last Release Error: {e}")
            last_version = None
        
        # Attempt to read the next release version (if a new release is detected)
        try:
            next_release_file = output_directory.file(NEXT_RELEASE_FILE)
            next_version = (await next_release_file.contents()).strip()
            print(f"Next release version: {next_version}")
        except QueryError as e:
            print("Next Release Error: ", e)
            next_version = None
        
        # Prepare the result as a JSON-encoded string
        result_json = { "last_release": last_version, "next_release": next_version }

        return json.dumps(result_json)
        


    def _configure_release_params(self):
        """
        Configure the .releaserc settings used by semantic-release based on the
        current branch, repository, and CI provider context.
        """
        # Add the current Git branch as a release branch
        self.releaserc.add_branch(self.branch)

        # Set the repository URL for changelog, tags, and release publishing
        self.releaserc.set_repository_url(self.repository_url)

        # Add commit analyzer plugin to determine release type (major/minor/patch) from commit messages
        self.releaserc.add_plugin("@semantic-release/commit-analyzer")

        # Add exec plugin to write release version numbers to output files for later inspection
        exec_plugin = [
            "@semantic-release/exec",
            {
                "analyzeCommitsCmd": f"echo ${{lastRelease.version}} > {LAST_RELEASE_FILE}",
                "verifyReleaseCmd": f"echo ${{nextRelease.version}} > {NEXT_RELEASE_FILE}",        
            }
        ]
        self.releaserc.add_plugin(exec_plugin)

        # Conditional configuration for GitHub CI/CD environments
        if self.ci_provider == CiProvider.GITHUB:
            # see https://github.com/semantic-release/github?tab=readme-ov-file#options
            # Configure the GitHub plugin to publish GitHub releases
            github_plugin = [
                "@semantic-release/github",
                {
                    "addReleases": "top", # Adds release info to the top of the GitHub release description
                }
            ]

            self.releaserc.add_plugin(github_plugin)

            # Add release notes generator plugin for automatic changelog generation
            self.releaserc.add_plugin("@semantic-release/release-notes-generator")

            # Apply user-defined flags to control release behavior in CI
            self.releaserc.set_dry_run(self.dry_run)
            self.releaserc.set_debug(self.debug)
            self.releaserc.set_ci(self.ci)
        else:
            # Local execution: enable dry-run and debug mode, disable CI mode
            print("No CI provider detected, running in local mode")
            self.releaserc.set_dry_run(True)
            self.releaserc.set_debug(True)
            self.releaserc.set_ci(False)


    async def _prepare_semantic_release_container(self, source: Directory) -> Container:
        """Prepare the container for running semantic release.
        This functions specifies the container image and the working directory and
        copies the source directory to the container"""
        return await dag.container().from_(SEMANTIC_RELEASE_IMAGE).with_directory(
            APP_DIR, source
        ).with_workdir(APP_DIR)

    async def _github_actions_runner(self, container: Container) -> Container:
        """Run semantic release in GitHub Actions. This mimics the GitHub Actions environment
        by setting the GITHUB_REF and GITHUB_ACTIONS environment variables.
        This is needed by semantic release to determine the current branch and to indicate that
        this is a GitHub Actions environment"""
        return await container.with_new_file(
            ".releaserc", contents=self.releaserc.to_string()
        ).with_exec(
            ["ls", "-la"]
        ).with_exec(
            ["cat", ".releaserc"]
        # Required for Semantic Release
        ).with_secret_variable("GITHUB_TOKEN", self.github_token
        ).with_env_variable("GITHUB_USERNAME", self.username
        ).with_env_variable("GITHUB_ACTOR", self.username
        ).with_env_variable("GITHUB_REF", f"refs/heads/{self.branch}"
        ).with_env_variable("GITHUB_ACTIONS", "true"
        ).with_exec(["npx", "semantic-release"])

    # Run local (Requires GITHUB_TOKEN environment variable)
    async def _local_runner(self, container: Container) -> Container:
        """Run semantic release locally. minimal plugins enabled"""
        return await container.with_new_file(
            ".releaserc", contents=self.releaserc.to_string()
        ).with_exec(
            ["ls", "-la"]
        ).with_exec(
            ["cat", ".releaserc"]
        ).with_exec(["npx", "semantic-release"])