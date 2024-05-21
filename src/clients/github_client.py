"""
Este módulo contém a classe GithubClient, que é usada para interagir com a API do Github.
A classe GithubClient pode ser usada para recuperar informações sobre commits, conteúdo de 
arquivos e patches de pull requests.
"""

import os
import logging
import requests
from github import Github


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GithubClient:
    """
    A client for interacting with the GitHub API to manage pull requests and repository content.
    """

    def __init__(self, token):
        """
        Initialize the GithubClient with a GitHub token.

        Args:
            token (str): The GitHub token for authentication.
        """
        try:
            self.client = Github(token)
            self.repo_name = os.getenv('GITHUB_REPOSITORY')
            self.repo = self.client.get_repo(self.repo_name)
            logging.info("Initialized GitHub client for repository: %s", self.repo_name)
        except Exception as e:
            logging.error("Error initializing GitHub client: %s", e)
            raise

    def get_pr(self, pr_id):
        """
        Retrieve a pull request by its ID.

        Args:
            pr_id (int): The pull request ID.

        Returns:
            PullRequest: The pull request object.
        """
        try:
            pr = self.repo.get_pull(pr_id)
            logging.info("Retrieved PR ID: %s", pr_id)
            return pr
        except Exception as e:
            logging.error("Error retrieving PR ID %s: %s", pr_id, e)
            raise

    def get_pr_comments(self, pr_id):
        """
        Retrieve comments from a pull request.

        Args:
            pr_id (int): The pull request ID.

        Returns:
            PaginatedList: The list of comments.
        """
        try:
            pr = self.get_pr(pr_id)
            comments = pr.get_issue_comments()
            logging.info("Retrieved comments for PR ID: %s", pr_id)
            return comments
        except Exception as e:
            logging.error("Error retrieving comments for PR ID %s: %s", pr_id, e)
            raise

    def post_comment(self, pr_id, body):
        """
        Post a comment to a pull request.

        Args:
            pr_id (int): The pull request ID.
            body (str): The comment body.

        Returns:
            IssueComment: The created comment.
        """
        try:
            pr = self.get_pr(pr_id)
            comment = pr.create_issue_comment(body)
            logging.info("Posted comment to PR ID: %s", pr_id)
            return comment
        except Exception as e:
            logging.error("Error posting comment to PR ID %s: %s", pr_id, e)
            raise

    def get_commit_files(self, commit):
        """
        Retrieve the files modified in a commit.

        Args:
            commit (Commit): The commit object.

        Returns:
            list: The list of files modified in the commit.
        """
        try:
            files = commit.files
            logging.info("Retrieved files for commit: %s", commit.sha)
            return files
        except Exception as e:
            logging.error("Error retrieving files for commit %s: %s", commit.sha, e)
            raise

    def get_file_content(self, commit_sha, filename):
        """
        Retrieve the content of a file at a specific commit.

        Args:
            commit_sha (str): The commit SHA.
            filename (str): The name of the file.

        Returns:
            str: The content of the file.
        """
        try:
            content = self.repo.get_contents(filename, ref=commit_sha).decoded_content.decode()
            logging.info("Retrieved content for file: %s at commit: %s", filename, commit_sha)
            return content
        except Exception as e:
            logging.error(
                "Error retrieving content for file %s at commit %s: %s",
                filename,
                commit_sha,
                e
            )
            raise

    def get_pr_patch(self, pr_id):
        """
        Retrieve the patch content of a pull request.

        Args:
            pr_id (int): The pull request ID.

        Returns:
            str: The patch content of the pull request.
        """
        try:
            url = f"https://api.github.com/repos/{self.repo_name}/pulls/{pr_id}"
            headers = {
                'Authorization': f"token {os.getenv('GITHUB_TOKEN')}",
                'Accept': 'application/vnd.github.v3.diff'
            }
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            logging.info("Retrieved patch for PR ID: %s", pr_id)
            return response.text
        except requests.RequestException as e:
            logging.error("Error retrieving patch for PR ID %s: %s", pr_id, e)
            raise
