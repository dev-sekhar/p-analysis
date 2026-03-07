import sys
import os
import subprocess
import datetime

# Files to manage
DOC_FILES = ['prompts.md', 'README.md', 'todo.md']

def check_staged_changes():
    """Check if any python code files are staged for commit."""
    result = subprocess.run(['git', 'diff', '--cached', '--name-only'], 
                          capture_output=True, text=True)
    staged_files = result.stdout.splitlines()
    return any(f.endswith('.py') for f in staged_files)

def update_docs():
    """Append a timestamp note to the docs to remind the user to update them."""
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    update_note = f"\n\n*Auto-note*: Code was changed at {now}. Please ensure this documentation is still accurate.\n"
    
    for doc in DOC_FILES:
        if os.path.exists(doc):
            with open(doc, 'a', encoding='utf-8') as f:
                f.write(update_note)
            print(f"Added update reminder to {doc}")
            
            # Stage the changed doc file so it goes into the current commit
            subprocess.run(['git', 'add', doc])

if __name__ == "__main__":
    if check_staged_changes():
        print("Python changes detected. Updating documentation reminders...")
        update_docs()
    else:
        print("No python changes detected. Documentation untouched.")
    
    sys.exit(0)
