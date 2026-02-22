import os
import platform
import subprocess
import sys
import json

# --- PROJECT GENESIS ---
def check_environment():
    print("🌍 Detecting Host Environment...")
    system = platform.system()
    print(f"🖥️  OS: {system}")
    
    # Check for core dependencies
    deps = ["python3", "docker", "ollama"]
    for dep in deps:
        try:
            subprocess.run([dep, "--version"], capture_output=True, check=True)
            print(f"✅ {dep} is active.")
        except:
            print(f"❌ {dep} is missing. Please install it to continue.")

def run_onboarding():
    print("\n🐣 INITIALIZING NEURAL PATHWAYS...")
    print("Welcome to Project Jarvis. Let's define my DNA.\n")
    
    config = {}
    config['host_name'] = input("What should I call you? (e.g., Master/User): ")
    config['jarvis_name'] = input("What is my name? (Default: Jarvis): ") or "Jarvis"
    config['sarcasm_level'] = input("Sarcasm Level (0-10): ")
    
    print("\n🧠 Configuring Cognitive Slots...")
    config['openrouter_key'] = input("Enter OpenRouter API Key (optional): ")
    
    # Generate IDENTITY.md
    with open("IDENTITY.md", "w") as f:
        f.write(f"# IDENTITY.md\n\n- Name: {config['jarvis_name']}\n- Role: Digital personal assistant\n- Vibe: Customized (Sarcasm: {config['sarcasm_level']}/10)\n")
    
    # Generate a skeleton CORE.md
    with open("CORE.md", "w") as f:
        f.write(f"# CORE.md\n\n- Host: {config['host_name']}\n- Goal: Optimized human-AI symbiosis.\n")

    print("\n🧬 Genesis Sequence Complete. DNA generated.")

def main():
    print("✨ PROJECT JARVIS // GENESIS PROTOCOL")
    check_environment()
    run_onboarding()
    print("\n🚀 Jarvis is now ready to breathe. Use 'openclaw start' to wake me.")

if __name__ == "__main__":
    main()
