"""
ChartUpdater: Dagger object for automating Helm chart version updates in GitHub repositories.
- Fetches current chart version from remote Chart.yaml (supports private repos)
- Increments semantic version
- Updates Chart.yaml and values file in repo, commits, and pushes changes
"""
from dagger import dag, function, object_type, Secret, Doc, QueryError, JSON
from typing import Annotated
import json

@object_type
class ChartUpdater:

    async def _update_chart_files(
        self,
        github_token: Annotated[Secret, Doc("GitHub token for authentication with GitHub (used for clone/push)")],
        helm_repo_url: Annotated[str, Doc("Git repository URL containing the Helm chart(s), e.g. 'https://github.com/org/repo.git'")],
        branch: Annotated[str, Doc("Git branch to update, e.g. 'main'")],
        values_json: Annotated[JSON, Doc("JSON object with all values to update, e.g. '{\"app_name\": \"my-app\", \"app_version\": \"1.2.3\", \"image\": {\"tag\": \"1.2.3\"}}'")],
        values_file: Annotated[str, Doc("Relative path to the values file to update (default: 'values.yaml'), e.g. 'values.yaml' or 'charts/my-app/values.yaml'")] = "values.yaml",
        chart_path: Annotated[str, Doc("Relative path to the chart directory containing Chart.yaml (default: '.'), e.g. '.' or 'charts/my-app'")] = ".",
    ) -> None:
        """
        Clone the repository, fetch Chart.yaml version, update Chart.yaml and values file with new versions, commit, and push changes.
        """
        repo_path = "/repo"
        chart_path = chart_path or "."
        values_file = values_file or "values.yaml"
        full_chart_path = f"{repo_path}/{chart_path}"

        # Parse values_json
        if isinstance(values_json, dict):
            app_name = values_json["app_name"]
            app_version = values_json["app_version"]
            values_dict = values_json
        else:
            value_dict = json.loads(values_json)
            app_name = value_dict["app_name"]
            app_version = value_dict["app_version"]
            values_dict = value_dict

        # Prepare container for git, yq, and helm operations
        container = (
            dag.container()
            .from_("alpine/helm:3.18.3")
            .with_exec(["apk", "add", "--no-cache", "git", "yq", "curl"])
            .with_secret_variable("GITHUB_TOKEN", github_token)
            .with_exec(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"])
            .with_exec(["git", "config", "--global", "user.name", "github-actions[bot]"])
            .with_workdir(repo_path)
            .with_exec(["git", "clone", "--branch", branch, helm_repo_url, "."])
            .with_workdir(full_chart_path)
        )

        # Fetch current chart version from Chart.yaml in the correct directory (support both root and subdir)
        chart_yaml_path = f"{full_chart_path}/Chart.yaml" if chart_path != "." else "Chart.yaml"
        chart_version = await (
            container
            .with_exec(["sh", "-c", f"yq eval '.version' '{chart_yaml_path}'"])
            .stdout()
        )
        chart_version = chart_version.strip()
        new_chart_version = self._increment_patch_version(chart_version)

        # Update Chart.yaml with new versions
        container = (
            container
            .with_exec(["yq", "-i", f'.version = "{new_chart_version}"', "Chart.yaml"])
            .with_exec(["yq", "-i", f'.appVersion = "{app_version}"', "Chart.yaml"])
        )
        # Recursively apply all key/values from values_json to the values file
        def apply_yq(container, d, prefix=""):
            for k, v in d.items():
                if isinstance(v, dict):
                    container = apply_yq(container, v, prefix + k + ".")
                else:
                    yq_key = "." + prefix + k
                    container = container.with_exec(["yq", "-i", f'{yq_key} = "{v}"', values_file])
            return container
        container = apply_yq(container, values_dict)
        # Set remote URL with token for push
        container = (
            container
            .with_exec([
                "sh", "-c",
                f'git remote set-url origin "https://x-access-token:$GITHUB_TOKEN@github.com/{helm_repo_url.split("/")[-2]}/{helm_repo_url.split("/")[-1]}.git"'
            ])
            .with_exec(["git", "add", "."])
            .with_exec([
                "git", "commit", "-m",
                f"Update {app_name}:{app_version} chart version to {new_chart_version}"
            ])
            .with_exec(["git", "push", "origin", branch])
        )
        await container.stdout()

    def _increment_patch_version(self, version: Annotated[str, Doc("Semantic version string, e.g. '1.2.3'")]) -> str:
        """
        Increment the patch part of a semantic version string (e.g., 1.2.3 -> 1.2.4).
        Returns the incremented version string.
        Raises ValueError if version format is invalid.
        """
        parts = version.strip().split(".")
        if len(parts) == 3:
            major, minor, patch = parts
            return f"{major}.{minor}.{int(patch) + 1}"
        raise ValueError(f"Invalid version format: {version}")

    @function
    async def updatechart(
        self,
        values_json: Annotated[JSON, Doc(
            "JSON object with all values to update, e.g. '{\"app_name\": \"my-app\", \"app_version\": \"1.2.3\", \"image\": {\"tag\": \"1.2.3\"}}'"
        )],
        github_token: Annotated[Secret, Doc("GitHub token for authentication with GitHub (used for clone/push)")],
        helm_repo_url: Annotated[str, Doc("Git repository URL containing the Helm chart(s), e.g. 'https://github.com/org/repo.git'")],
        branch: Annotated[str, Doc("Git branch to update, e.g. 'main'")],
        values_file: Annotated[str, Doc("Relative path to the values file to update (default: 'values.yaml'), e.g. 'values.yaml' or 'charts/my-app/values.yaml'")] = "values.yaml",
        chart_path: Annotated[str, Doc("Relative path to the chart directory containing Chart.yaml (default: '.'), e.g. '.' or 'charts/my-app'")] = ".",
    ) -> None:
        """
        Main entrypoint: Update the Helm chart version and app version in Chart.yaml and values file.
        Raises QueryError if fetching or incrementing chart version fails.
        """
        chart_path = chart_path or "."
        values_file = values_file or "values.yaml"
        try:
            await self._update_chart_files(
                github_token=github_token,
                helm_repo_url=helm_repo_url,
                branch=branch,
                values_json=values_json,
                values_file=values_file,
                chart_path=chart_path,
            )
        except Exception as e:
            print(f"Error updating chart files: {e}")
            raise QueryError(f"Failed to update chart files: {e}")