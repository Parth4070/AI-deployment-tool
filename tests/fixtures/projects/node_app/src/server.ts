// Sample app for scanner tests. Not a real service.
import express from "express";

const app = express();
const PORT: number = Number(process.env.PORT || 3000);
const { STRIPE_KEY, MAIL_HOST: mailHost } = process.env;
const token = process.env["AUTH_TOKEN"] as string;
// process.env.ONLY_IN_A_COMMENT must not be reported.

app.listen(PORT, () => console.log(STRIPE_KEY, mailHost, token));
