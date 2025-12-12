from flask import Flask, request # type: ignore
import sqlite3

DB_PATH = "emails.db"

app = Flask(__name__)

@app.get("/update_open")
def update_open():
    tid = request.args.get("tid")
    if not tid:
        return "no tid", 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE leads SET opened = 1 WHERE tracking_id = ?", (tid,))
    conn.commit()
    conn.close()

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
