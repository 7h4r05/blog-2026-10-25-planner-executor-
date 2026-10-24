
from agents.state_executor import StateExecutor
from agents.code_executor import CodeExecutor
from agents.response_agent import ResponseAgent
from core.mcp_client import TerraformMCPClient


class AgentManager:

    def __init__(self, llm):
        self.llm = llm

        mcp_client = TerraformMCPClient()
        state_executor = StateExecutor(llm=llm, mcp_client=mcp_client)
        code_executor = CodeExecutor(llm=llm)
        response_agent = ResponseAgent(llm=llm)

        self.__agents = [state_executor, code_executor, response_agent]


    def get_agents(self):
        return list(self.__agents)
