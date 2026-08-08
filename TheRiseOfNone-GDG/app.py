from flask import Flask, render_template, request

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login", methods=["POST"])
def login():

    username = request.form.get("username")
    password = request.form.get("password")

    print("Username:", username)
    print("Password:", password)

    return f"""
        <h1>Login Received</h1>
        <p>Username: {username}</p>
        <p>Password received successfully.</p>
    """


if __name__ == "__main__":
    app.run(debug=True)
