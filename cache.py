from flask import Flask, make_response
from random import randrange
import time

app = Flask(__name__)

@app.route("/")
def home():
    resp = make_response("<h1>Cache [status]</h1>")
    resp.headers['Cache-Control'] = 'public, max-age=2'
    return resp

@app.route("/no-cache")
def no_cache():
    resp = make_response("<h1>Cache [status]</h1>")
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route("/private")
def private():
    resp = make_response("<h1>Cache [status]</h1>")
    resp.headers['Cache-Control'] = 'private, max-age=360'
    return resp

@app.route("/stale-while-revalidation")
def stale_while_revalidation():
    time.sleep(3)
    resp = make_response("<h1>Cache [status]</h1>")
    resp.headers['Cache-Control'] = 'public, max-age=2, stale-while-revalidate=360'
    return resp

@app.route("/stale-if-error")
def stale_if_error():
    resp = make_response("<h1>Cache [status]</h1>")
    resp.headers['Cache-Control'] = 'public, max-age=2, stale-if-error=360'
    if randrange(3) == 1:
        return 'Internal Server Error', 500
    return resp

@app.route("/no-stale-if-error")
def no_stale_if_error():
    resp = make_response("<h1>Cache [status]</h1>")
    resp.headers['Cache-Control'] = 'public, max-age=2'
    if randrange(3) == 1:
        return 'Internal Server Error', 500
    return resp

if __name__ == "__main__":
    app.run(debug=True)
