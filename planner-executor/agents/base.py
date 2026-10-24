
from abc import ABC, abstractmethod


class BaseAgent(ABC):
    name = "base"
    description = "Base agent."

    def __init__(self, llm=None):
        self.llm = llm

    @abstractmethod
    def run(self, task):
        raise NotImplementedError

