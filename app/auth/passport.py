from fastapi import Depends

from app.auth.strategies.base import BaseStrategy


class Passport:
    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}

    def use(self, name: str, strategy: BaseStrategy) -> "Passport":
        self._strategies[name] = strategy
        return self

    def authenticate(self, name: str):
        """Return a FastAPI Depends that runs the named strategy.

        Usage (mirrors passport.authenticate('jwt') in Passport.js):
            current_socio: Socio = passport.authenticate("jwt")
        """
        strategy = self._strategies[name]
        return Depends(strategy.as_dependency())
