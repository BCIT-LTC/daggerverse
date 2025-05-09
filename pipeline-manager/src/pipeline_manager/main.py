from dagger import dag, function, object_type, DefaultPath, Directory, Secret, Doc, Enum, enum_type
from typing import Annotated
import json
from datetime import datetime

# Constants
MAIN_BRANCH = "main"

@enum_type
class Environment(Enum):
    STABLE          = "stable"        # latest version ( main branch commit includes semver format)
    LATEST          = "latest"        # latest version ( main branch commit without semver format)
    REVIEW          = "review"        # review version ( not on main branch )
    LOCAL           = "local"         # local environment
    LATEST_STABLE   = "latest_stable" # could be either latest or stable (transition state)
    CI              = "ci"            # token found    (transition state)
    NONE            = "none"          # undefined      (transition state)


@object_type
class PipelineManager:
    environment = Environment.NONE
    semantic_release_result = None
    version = None
    tags = None
    docker_container = None

    async def _check_if_ci(self) -> None:
        """
        Check if the environment is CI or local
        """
        # Check if GitHub token is provided
        if self.github_token is not None:
            print("Running in CI environment")
            self.environment = Environment.CI
        else:
            print("Running locally")
            self.environment = Environment.LOCAL


    async def _check_if_review(self) -> str:
        """
        Determine if running on a review branch or main branch
        """
        if self.branch == MAIN_BRANCH:
            print("Running on Main branch")
            self.environment = Environment.LATEST_STABLE
        else:
            print("Running on Review branch")
            self.environment = Environment.REVIEW


    async def _create_tag(self) -> None:
        """
        Create a tag for the release
        """
        # Get the current date and time
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_timestamp = now.strftime(current_date + "%s")

        if self.environment == Environment.STABLE:
            self.tags = [self.version, Environment.STABLE.value, Environment.LATEST.value]
            print("Tags created for STABLE: ", self.tags)
        elif self.environment == Environment.LATEST:
            self.tags = [f"{self.version}-{self.commit_hash}.{current_timestamp}", Environment.LATEST.value]
            print("Tags created for LATEST: ", self.tags)
        elif self.environment == Environment.REVIEW:
            self.tags = [f"review-{self.branch}-{self.commit_hash}.{current_timestamp}"]
            print("Tag created for REVIEW: ", self.tags)
        else:
            # self.tags = [] # for debugging purposes
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
        Publish the Docker image to a registry.
        """
        print("Publishing Docker image...")
        # parse self.tags that is comma separated
        final_container = await (
                self.docker_container
                .with_registry_auth(self.registry_path, self.username, self.github_token)
            )
  
        # Publish the image for each tag
        for tag in self.tags:
            await final_container.publish(f"{self.registry_path}:{tag}")
    
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
        Run semantic release if the environment is either latest or stable
        """
        if self.environment == Environment.LATEST_STABLE:
            print("Running semantic release...")
            print(dag.semantic_release())
            self.semantic_release_result = await dag.semantic_release().semanticrelease(
                source=self.source,
                github_token=self.github_token,
                username=self.username,
                repository_url=self.repository_url
            )
            print("Semantic Release Result: ", self.semantic_release_result)
            self.semantic_release_result = json.loads(self.semantic_release_result)
            print("Next Release: ", self.semantic_release_result['next_release'])
            if self.semantic_release_result['next_release']:
                self.environment = Environment.STABLE
                self.version = self.semantic_release_result['next_release']
            else:
                self.environment = Environment.LATEST
                self.version = self.semantic_release_result['last_release']
        else:
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
        Run the pipeline manager to build and publish a Docker image.
        """

        print(dir(dag))
        # Set function arguments as class variables
        self.source = source
        self.github_token = github_token
        self.username = username
        self.branch = branch
        self.commit_hash = commit_hash
        self.registry_path = registry_path
        self.repository_url = repository_url

        # Run unit tests
        await self.unit_tests()

        # Determine if ci environment by checking for GitHub token
        await self._check_if_ci()

        # Build the Docker image
        await self._build_docker_image()
        
        # Determine the environment
        await self._check_if_review()

        # Run semantic release
        await self.run_semantic_release()
    
        # Create tag
        await self._create_tag()

        print(f"Tags: {self.tags}, Environment: {self.environment}")

        # Publish the Docker image
        await self._publish_docker_image()
        print("Pipeline completed successfully")
    

            
