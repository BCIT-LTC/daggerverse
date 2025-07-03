from dagger import dag, function, object_type, DefaultPath, Directory, Secret, Doc, Enum, enum_type
from typing import Annotated
import json
from datetime import datetime

# Constants
MAIN_BRANCH = "main"

@enum_type
class Environment(Enum):
    STABLE              = "stable"              # latest version ( main branch commit includes semver format)
    LATEST              = "latest"              # latest version ( main branch commit without semver format)
    REVIEW              = "review"              # review version ( not on main branch )
    LOCAL               = "local"               # local environment
    LATEST_OR_STABLE    = "latest_or_stable"    # could be either latest or stable (transition state)
    CI                  = "ci"                  # token found    (transition state)
    NONE                = "none"                # undefined      (transition state)


@object_type
class PipelineManager:
    environment = Environment.NONE
    semantic_release_result = None
    version = None
    tags = None
    docker_container = None

    async def _check_if_ci(self) -> None:
        """
        Check if the current environment is a CI pipeline or a local development setup.
        Sets the environment to Environment.CI or Environment.LOCAL accordingly.
        """
        # Check if the GitHub token is set, which usually indicates a CI environment
        if self.github_token is not None:
            print("Running in CI environment")
            self.environment = Environment.CI
        else:
            # If the token is missing, assume it's a local development context
            print("Running locally")
            self.environment = Environment.LOCAL


    async def _check_if_review(self) -> str:
        """
        Determine the environment type based on the current Git branch.
        Sets the environment to:
        - LATEST_OR_STABLE if on the main branch
        - REVIEW if on any other branch (typically a feature, PR, or test branch)
        """
        # If the current branch is the main branch, treat it as a candidate for stable/latest release
        if self.branch == MAIN_BRANCH:
            print("Running on Main branch")
            self.environment = Environment.LATEST_OR_STABLE
        else:
            # Any other branch is treated as a review (non-production) environment
            print("Running on Review branch")
            self.environment = Environment.REVIEW


    async def _create_tag(self) -> None:
        """
        Create appropriate tags for the release based on the current environment.
        Tags vary for STABLE, LATEST, and REVIEW environments.
        """
        # Get the current date and time
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        # Generate a timestamp string with current date and Unix time
        current_timestamp = now.strftime(current_date + "%s")

        # Tag logic for STABLE environment
        if self.environment == Environment.STABLE:
            # Use version number and both 'stable' and 'latest' tags
            self.tags = [self.version, Environment.STABLE.value, Environment.LATEST.value]
            print("Tags created for STABLE: ", self.tags)
        # Tag logic for LATEST environment
        elif self.environment == Environment.LATEST:
            # Create a tag with version, commit hash, and timestamp, along with 'latest'
            self.tags = [f"{self.version}-{self.commit_hash}.{current_timestamp}", Environment.LATEST.value]
            print("Tags created for LATEST: ", self.tags)
        # Tag logic for REVIEW environment
        elif self.environment == Environment.REVIEW:
            # Create a review tag that includes branch name and commit hash
            self.tags = [f"review-{self.branch}-{self.commit_hash}.{current_timestamp}"]
            print("Tag created for REVIEW: ", self.tags)
        else:
            # Handle unknown environments (no tags created)
            # self.tags = []  # Uncomment for debugging or fallback behavior
            print("No tag created for this environment")
            
    
    async def _build_docker_image(self) -> None:
        """
        Build the Docker image using the source directory.
        """
        print("Building Docker image...")
        try:
            self.docker_container = await self.source.docker_build()
        except Exception as e:
            print(f"Error building Docker image: {e}")
            raise
        print("Docker image built successfully")


    async def _publish_docker_image(self) -> None:
        """
        Publish the built Docker image to a container registry using all configured tags.
        """
        print("Publishing Docker image...")
        # Authenticate with the container registry using credentials
        final_container = await (
                self.docker_container
                .with_registry_auth(self.registry_path, self.username, self.github_token)
            )
  
        # Iterate over all tags and publish the image under each tag
        for tag in self.tags:
            # Push the Docker image to the registry with the specific tag
            await final_container.publish(f"{self.registry_path}:{tag}")
        # Print a summary of all tags that were published
        print(f"Published with tags: {', '.join(self.tags)}")


    @function
    async def unit_tests(self) -> None:
        """
        Run unit tests by calling the test function in the source directory.
        This function is a placeholder and should be replaced with actual test logic.
        """
        print("Running unit tests...")
        # Add your unit test logic here
        # For example, you can use pytest to run tests in the source directory
        # await self.source.run("pytest", args=["-v", "--tb=short"])
        

    @function
    async def run_semantic_release(self) -> str:
        """
        Run semantic-release and update the environment and version based on the result.
        Only runs if the environment is LATEST_OR_STABLE.
        """
        if self.environment == Environment.LATEST_OR_STABLE:
            print("Running semantic release...")
            # Preview the semantic release DAG invocation (optional debug output)
            print(dag.semantic_release())
            # Execute the semantic-release process using provided configuration
            self.semantic_release_result = await dag.semantic_release().semanticrelease(
                source=self.source,
                github_token=self.github_token,
                username=self.username,
                repository_url=self.repository_url
            )
            # Output the raw result for debugging
            print("Semantic Release Result: ", self.semantic_release_result)
            # Parse the JSON result into a dictionary
            self.semantic_release_result = json.loads(self.semantic_release_result)
            # Log the next release version if available
            print("Next Release: ", self.semantic_release_result['next_release'])
            # Update internal state based on the release result
            if self.semantic_release_result['next_release']:
                # If a new release is detected, mark environment as STABLE
                self.environment = Environment.STABLE
                self.version = self.semantic_release_result['next_release']
            else:
                # Otherwise, fallback to LATEST using the last known release
                self.environment = Environment.LATEST
                self.version = self.semantic_release_result['last_release']
        else:
            # Skip semantic-release for other environments (e.g., REVIEW)
            print("Not running semantic release for this environment")
            self.semantic_release_result = None


    @function
    async def run(self,
                source: Annotated[Directory, Doc("Source directory"), DefaultPath(".")], # source directory
                github_token: Annotated[Secret | None, Doc("Github Token")],
                username: Annotated[str | None, Doc("Github Username")],  # GitHub username
                branch: Annotated[str | None, Doc("Current Branch")],  # Current branch
                commit_hash: Annotated[str | None, Doc("Current Commit Hash")],  # Current commit hash
                registry_path: Annotated[str | None, Doc("Docker Registry Path")],  # Docker registry path
                repository_url: Annotated[str | None, Doc("Repository URL")],  # Repository URL
                  ) -> None:
        """
        Main pipeline entry point.
        Builds, tags, and publishes a Docker image depending on the environment context.
        """
        # Optional: print DAG functions available (useful for debugging Dagger CLI setup)
        print(dir(dag))

        # Store all function parameters as instance variables for use in downstream methods
        self.source = source
        self.github_token = github_token
        self.username = username
        self.branch = branch
        self.commit_hash = commit_hash
        self.registry_path = registry_path
        self.repository_url = repository_url

        # Step 1: Run unit tests to ensure build correctness
        await self.unit_tests()

        # Step 2: Determine if running in CI or local by checking GitHub token presence
        await self._check_if_ci()

        # Step 3: Build the Docker image from the source directory
        await self._build_docker_image()
        
        # Step 4: Identify whether this is a review branch or a stable/main branch
        await self._check_if_review()

        # Step 5: Run semantic-release to determine version and update environment
        await self.run_semantic_release()
    
        # Step 6: Create image tags based on environment, version, branch, and commit hash
        await self._create_tag()
        print(f"Tags: {self.tags}, Environment: {self.environment}")

        # Step 7: Push the Docker image to the container registry using generated tags
        await self._publish_docker_image()
        print("Pipeline completed successfully")
    

            
