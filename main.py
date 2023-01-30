# Automated Code Review using the ChatGPT language model

## Import statements
import argparse
import openai
import os
from github import Github

## Adding command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--openai_api_key', help='Your OpenAI API Key')
parser.add_argument('--github_token', help='Your Github Token')
parser.add_argument('--github_pr_id', help='Your Github PR ID')
parser.add_argument('--openai_engine', default="text-davinci-002", help='GPT-3 model to use. Options: text-davinci-002, text-babbage-001, text-curie-001, text-ada-001')
parser.add_argument('--openai_temperature', default=0.5, help='Sampling temperature to use. Higher values means the model will take more risks. Recommended: 0.5')
parser.add_argument('--openai_max_tokens', default=2048, help='The maximum number of tokens to generate in the completion.')
args = parser.parse_args()

## Authenticating with the OpenAI API
openai.api_key = args.openai_api_key

## Authenticating with the Github API
g = Github(args.github_token)

## Selecting the repository
repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))

## Get pull request
pull_request = repo.get_pull(int(args.github_pr_id))

## Loop through the commits in the pull request
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
            engine=args.openai_engine,
            prompt=(f"Explain Code:\n```{content}```"),
            temperature=float(args.openai_temperature),
            max_tokens=int(args.openai_max_tokens)
        )

        # Adding a comment to the pull request with ChatGPT's response
        pull_request.create_issue_comment(f"ChatGPT's response about `{file.filename}`:\n {response['choices'][0]['text']}")
