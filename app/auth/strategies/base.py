from abc import ABC, abstractmethod
from typing import Callable


class BaseStrategy(ABC):
    @abstractmethod
    def as_dependency(self) -> Callable:
        """Return a FastAPI-injectable callable that authenticates the request."""
