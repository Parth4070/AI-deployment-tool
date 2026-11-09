// Sample app where every preflight check fails. Not a real service.
const express = require("express");

const app = express();
const db = process.env.DATABASE_URL;

app.get("/", (req, res) => res.send("hello"));
app.listen(3000);
