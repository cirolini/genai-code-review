"""This project aims to automate code review using the ChatGPT language model."""
import argparse
import openai
import os
from github import Github

# Adding command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--openai_api_key', help='Your OpenAI API Key')
parser.add_argument('--github_token', help='Your Github Token')
parser.add_argument('--github_pr_id', help='Your Github PR ID')
args = parser.parse_args()

# Authenticating with the OpenAI API
openai.api_key = args.openai_api_key

# Authenticating with the Github API
g = Github(args.github_token)

# Selecting the repository
repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))

# Get pull request
pull_request = repo.get_pull(int(args.github_pr_id))

commits = pull_request.get_commits()
for commit in commits:
    # Getting the modified files in the commit
    files = commit.files
    for file in files:
        # Getting the file name and content
        filename = file.filename
        content = repo.get_contents(filename, ref=commit.sha).decoded_content

        # Sending the code to ChatGPT
        response = openai.Completion.create(
            engine="text-davinci-002",
            prompt=(f"Explain Code:\n```{content}```"),
            temperature=0.5,
            max_tokens=2048
        )

        # Adding a comment to the pull request with ChatGPT's response
        pull_request.create_issue_comment(f"ChatGPT's response to explain this code:\n {response['choices'][0]['text']}")
