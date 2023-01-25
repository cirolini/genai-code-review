# Code Review with ChatGPT

This project aims to automate code review using the ChatGPT language model. It connects to the Github API to select a specific repository and list the existing pull requests. Then it sends each code review to ChatGPT and asks for an evaluation on it.

## Prerequisites
- Python 3.8+
- [openai](https://openai.com/) API Key
- [Github](https://github.com/) API Key
- [PyGithub](https://pypi.org/project/PyGithub/)
- [requests](https://pypi.org/project/requests/)

## Installation
1. Clone this repository
```
git clone https://github.com/OWNER/REPO.git
````

2. Install the dependencies
```
pip install -r requirements.txt
```

3. Add your openai and Github API key to your environment variables

## Usage
Run the main.py script
```
python main.py
````

## Contributing
Feel free to contribute to the project. Any suggestion or correction will be greatly appreciated.

## License
This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
