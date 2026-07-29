import re

css_file = r'c:\xampp\htdocs\machinewin_php\style.css'

with open(css_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Define comprehensive color replacements
replacements = [
    ('background: white;', 'background: var(--bg-secondary);'),
    ('border-top: 1px solid #e5e7eb;', 'border-top: 1px solid var(--border-color);'),
    ('border: 1px solid #e5e7eb;', 'border: 1px solid var(--border-color);'),
    ('border-bottom: 1px solid #e5e7eb;', 'border-bottom: 1px solid var(--border-color);'),
    ('color: #374151;', 'color: var(--text-secondary);'),
    ('color: #6b7280;', 'color: var(--text-secondary);'),
    ('background: #eab308;', 'background: var(--accent-color);'),
    ('background: #ca8a04;', 'background: var(--accent-dark);'),
    ('color: #eab308;', 'color: var(--accent-color);'),
    ('border: 1px solid #eab308;', 'border: 1px solid var(--accent-color);'),
    ('color: #000;', 'color: var(--text-primary);'),
]

changes = 0
for old, new in replacements:
    count = content.count(old)
    if count > 0:
        content = content.replace(old, new)
        changes += count
        print(f"Replaced {count}x: {old[:30]}... → {new[:30]}...")

with open(css_file, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\nTotal replacements: {changes}")
print("CSS file updated successfully!")
