# 🧠 Automation to Autonomy: Autonomous IT Support Agent (PoC)

This project is a Proof-of-Concept (PoC) of an intelligent, agent-based, end-to-end autonomous IT support system. It leverages Large Language Models (LLMs), multi-agent collaboration, and DevOps automation tools (Vagrant, Ansible) to spin up, provision, monitor, and manage infrastructure dynamically with minimal human input.

Built with a simple Flask web UI, the system takes user queries like:

* "Set up my full application stack"
* "Restart Tomcat"
* "Install RabbitMQ"
* "Check disk usage on all servers"

It then autonomously executes these using intelligent agents.

🚀 Project Goals

* Demonstrate an LLM-driven, multi-agent AI system
* Use open-source components and local infrastructure
* Minimize resource dependency (runs fully on local laptop)
* Show how traditional ITSM support (like ServiceNow) can be simulated via file-based ticketing

🧱 Tech Stack

Frontend/UI:

* Flask Web Portal (for now; MS Teams integration planned)

Backend Logic:

* LangChain + CrewAI → Agent orchestration
* Ollama (Mistral) → Local LLM inference
* Python (agent logic + utilities)
* JSON/CSV → File-based ticketing

Infrastructure:

* Vagrant → Local VM provisioning
* Ansible → Configuration management
* VirtualBox → VM Provider

📂 Project Structure

autonomous-it-support/
├── app/
│   ├── templates/
│   │   └── index.html      → Web UI for user input
│   ├── static/
│   │   └── style.css       → Professional blue-themed styling
│   ├── app.py              → Flask app (runs UI and agents)
├── agents/
│   ├── planner\_agent.py    → Breaks request into tasks
│   ├── infra\_agent.py      → Edits and manages Vagrantfile
│   ├── provisioner\_agent.py→ Triggers Ansible provisioning
│   ├── adhoc\_agent.py      → Handles unstructured user commands
│   ├── logger\_agent.py     → Logs all activity to JSON file
├── llm/
│   └── ollama\_config.py    → Loads and configures Mistral model
├── ansible/
│   ├── playbooks/          → YAML files to install services
│   ├── inventory/          → Ansible hosts
├── vagrant/
│   └── Vagrantfile         → Defines 6-7 VM topology
├── tickets/
│   └── tickets.json        → File-based mock for ServiceNow
├── requirements.txt        → Python dependencies
└── README.md               → This file

🧠 Agents Overview

| Agent            | Role                                       |
| ---------------- | ------------------------------------------ |
| PlannerAgent     | Interprets user prompt and sequences tasks |
| InfraAgent       | Modifies Vagrantfile to define VM layout   |
| ProvisionerAgent | Triggers Ansible playbooks for setup       |
| AdhocAgent       | Responds to commands like "restart nginx"  |
| LoggerAgent      | Logs actions to file (ticketing mechanism) |

📦 Services Provisioned

The following services can be provisioned on VMs in the exact order:

1. MySQL – Database Service
2. Memcache – Database Caching
3. RabbitMQ – Message Broker
4. Tomcat – Application Server
5. Elasticsearch – Search Engine
6. Nginx – Web Server

✅ Sample Use Cases

* Spin up a complete 6-VM microservices stack
* Ask the agent to install Redis on-demand
* Restart a specific service via prompt
* Run diagnostics (e.g., check disk/memory usage)
* Log each step as a ticket in JSON format

⚙️ How It Works (Flow)

1. User submits a request via the web portal.
2. PlannerAgent breaks it into infrastructure + provisioning tasks.
3. InfraAgent modifies Vagrantfile and spins up VMs.
4. ProvisionerAgent installs the services using Ansible.
5. LoggerAgent logs the action with timestamp in tickets.json.
6. If user makes ad-hoc request → AdhocAgent handles it directly.

🖥️ Running the Project

Pre-requisites:

* Python 3.10+
* Vagrant + VirtualBox
* Ollama with Mistral model installed
* Ansible installed on your laptop

1. Clone repo

git clone [https://github.com/shashikantdev3/Automation-to-Autonomy-Autonomous-IT-Support-Agent]((https://github.com/shashikantdev3/Automation-to-Autonomy-Autonomous-IT-Support-Agent))
cd autonomous-it-support

2. Start Flask Web App

pip install -r requirements.txt
python app/app.py

3. Interact via Web UI

* Type requests like “Set up app stack”
* View ticket log in tickets/tickets.json

📚 Future Enhancements

* MS Teams chatbot interface
* Real ServiceNow integration via REST APIs
* Monitoring & alerting dashboard
* Use of GPU-based LLM (Mixtral/CodeGemma)

📄 License

MIT License
