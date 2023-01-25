# Code Review with ChatGPT

This project aims to automate code review using the ChatGPT language model. It integrates  with Github Actions, and upon receiving a Pull Request, it automatically sends each code review to ChatGPT for an explanation.

# Prerequisite

First, you will need a personal API key from OpenAI which you can get here: https://openai.com/api/. To get an OpenAI API key, you can sign up for an account on the OpenAI website https://openai.com/signup/. Once you have signed up, you can create a new API key from your account settings.

After creating your API Key in OpenAI, create it as a secret in your repository or organization with the following name: openai_api_key.

You can do this by going to your repository/organization's settings, navigate to secrets and create a new secret with the name 'openai_api_key' and paste your OpenAI API key as the value.

Then you need to set up your project's permissions so that the Github Actions can write comments on Pull Requests. You can read more about this here: https://docs.github.com/en/actions/security-guides/automatic-token-authentication#modifying-the-permissions-for-the-github_token

C