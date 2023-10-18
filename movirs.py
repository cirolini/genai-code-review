# 1. Install required packages
# pip install Flask IMDbPY

from flask import Flask, jsonify, request
from imdb import IMDb

app = Flask(__name__)
ia = IMDb()

@app.route('/movie', methods=['GET'])
def get_movie():
    # Get movie title from query parameter
    title = request.args.get('title', '')

    # Search for the movie in IMDB
    movies = ia.search_movie(title)

    if not movies:
        return jsonify({'error': 'Movie not found'}), 404

    # Get the first match (you can adjust to get more results if desired)
    movie = movies[0]

    # Fetch detailed information for the movie
    ia.update(movie)

    # Extract desired details
    data = {
        'title': movie.get('title'),
        'year': movie.get('year'),
        'genres': movie.get('genres'),
        'director': [person['name'] for person in movie.get('director', [])],
        'plot': movie.get('plot outline'),
        'rating': movie.get('rating'),
        'votes': movie.get('votes'),
        'runtime': movie.get('runtime'),
        'cast': [person['name'] for person in movie.get('cast', [])][:5]  # top 5 actors
    }

    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True)
