import unittest
from unittest.mock import patch, MagicMock
from clients.github_client import GithubClient
import os

class TestGithubClient(unittest.TestCase):

    def setUp(self):
        self.token = "fake_github_token"
        self.repo_name = "fake_repo"
        self.pr_id = 1
        self.commit_sha = "fake_commit_sha"
        self.filename = "fake_file.py"

        os.environ['GITHUB_REPOSITORY'] = self.repo_name
        os.environ['GITHUB_TOKEN'] = self.token

        with patch('clients.github_client.Github') as MockGithub:
            self.mock_github = MockGithub.return_value
            self.mock_repo = self.mock_github.get_repo.return_value
            self.github_client = GithubClient(self.token)

    def tearDown(self):
        del os.environ['GITHUB_REPOSITORY']
        del os.environ['GITHUB_TOKEN']

    def test_init(self):
        self.mock_github.get_repo.assert_called_with(self.repo_name)
        self.assertEqual(self.github_client.repo_name, self.repo_name)
        self.assertEqual(self.github_client.repo, self.mock_repo)

    def test_get_pr(self):
        mock_pr = MagicMock()
        self.mock_repo.get_pull.return_value = mock_pr
        pr = self.github_client.get_pr(self.pr_id)
        self.mock_repo.get_pull.assert_called_with(self.pr_id)
        self.assertEqual(pr, mock_pr)

    def test_get_pr_comments(self):
        mock_pr = MagicMock()
        mock_comments = MagicMock()
        self.mock_repo.get_pull.return_value = mock_pr
        mock_pr.get_issue_comments.return_value = mock_comments

        comments = self.github_client.get_pr_comments(self.pr_id)
        self.mock_repo.get_pull.assert_called_with(self.pr_id)
        mock_pr.get_issue_comments.assert_called_once()
        self.assertEqual(comments, mock_comments)

    def test_post_comment(self):
        mock_pr = MagicMock()
        mock_comment = MagicMock()
        self.mock_repo.get_pull.return_value = mock_pr
        mock_pr.create_issue_comment.return_value = mock_comment

        body = "Test comment"
        comment = self.github_client.post_comment(self.pr_id, body)
        self.mock_repo.get_pull.assert_called_with(self.pr_id)
        mock_pr.create_issue_comment.assert_called_with(body)
        self.assertEqual(comment, mock_comment)

    def test_get_commit_files(self):
        mock_commit = MagicMock()
        mock_commit.files = ["file1.py", "file2.py"]
        files = self.github_client.get_commit_files(mock_commit)
        self.assertEqual(files, ["file1.py", "file2.py"])

    def test_get_file_content(self):
        mock_content = MagicMock()
        mock_content.decoded_content.decode.return_value = "file content"
        self.mock_repo.get_contents.return_value = mock_content

        content = self.github_client.get_file_content(self.commit_sha, self.filename)
        self.mock_repo.get_contents.assert_called_with(self.filename, ref=self.commit_sha)
        self.assertEqual(content, "file content")

    @patch('clients.github_client.requests.get')
    def test_get_pr_patch(self, mock_get):
        mock_response = MagicMock()
        mock_response.text = "patch content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        patch_content = self.github_client.get_pr_patch(self.pr_id)
        expected_url = f"https://api.github.com/repos/{self.repo_name}/pulls/{self.pr_id}"
        mock_get.assert_called_with(expected_url, headers={
            'Authorization': f"token {self.token}",
            'Accept': 'application/vnd.github.v3.diff'
        }, timeout=60)
        self.assertEqual(patch_content, "patch content")

if __name__ == '__main__':
    unittest.main()
