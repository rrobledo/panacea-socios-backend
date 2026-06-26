from app.auth.passport import Passport
from app.auth.strategies.apple import AppleStrategy
from app.auth.strategies.facebook import FacebookStrategy
from app.auth.strategies.google import GoogleStrategy
from app.auth.strategies.jwt import JWTStrategy
from app.auth.strategies.local import LocalStrategy
from app.auth.strategies.register import RegisterStrategy

passport = (
    Passport()
    .use("local", LocalStrategy())
    .use("jwt", JWTStrategy())
    .use("google", GoogleStrategy())
    .use("facebook", FacebookStrategy())
    .use("apple", AppleStrategy())
    .use("register", RegisterStrategy())
)
