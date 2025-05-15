from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

llm = Ollama(model="mistral", temperature=0.2)

# General knowledge query
async def knowledge_query(question: str) -> str:
    prompt = PromptTemplate(
        input_variables=["question"],
        template="""
        You are an expert IT assistant. Answer the following question in a clear, concise, and actionable way:
        
        Question: {question}
        """
    )
    chain = LLMChain(llm=llm, prompt=prompt)
    return chain.run(question=question)

# Remediation plan generation
async def generate_remediation(issue: str, service: str, server: str) -> str:
    prompt = PromptTemplate(
        input_variables=["issue", "service", "server"],
        template="""
        Given the following issue with {service} on {server}, provide a detailed resolution plan:
        
        Issue: {issue}
        
        Your response should include:
        1. Issue analysis
        2. Step-by-step resolution with commands
        3. Validation steps
        4. Rollback procedures
        5. Risk assessment
        
        Format as JSON.
        """
    )
    chain = LLMChain(llm=llm, prompt=prompt)
    return chain.run(issue=issue, service=service, server=server) 