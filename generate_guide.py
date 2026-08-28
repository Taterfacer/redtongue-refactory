#!/usr/bin/env python3
"""
generate_guide.py
Generates the 'Idiot's Guide to RedTongue Refactory' PDF 
matching the application's dark UI theme.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# Theme colors matching ui_main.py
C_BG = "#0d0d0d"  # Background
C_PANEL = "#121212"  # Panel
C_INPUT = "#1a1a1a"  # Input fields
C_RED = "#8b0000"  # Primary accent
C_RED_HOVER = "#a52a2a"  # Hover state
C_WHITE = "#e0e0e0"  # Text
C_GRAY = "#888888"  # Secondary text
C_GREEN = "#2ecc71"  # Success

def generate_pdf(output_path="RedTongue_ Idiots_Guide.pdf"):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
        title="RedTongue Refactory - Idiot's Guide"
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles matching app theme
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor(C_RED),
        spaceAfter=30,
        alignment=1,  # Center
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=colors.HexColor(C_GRAY),
        spaceAfter=20,
        alignment=1,
        fontName='Helvetica-Oblique'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=18,
        textColor=colors.HexColor(C_RED),
        spaceBefore=20,
        spaceAfter=12,
        fontName='Helvetica-Bold'
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor("#333333"),  # Dark gray for readability on white paper
        spaceAfter=10,
        leading=16
    )
    
    note_style = ParagraphStyle(
        'Note',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor(C_RED),
        spaceBefore=5,
        spaceAfter=5,
        fontName='Helvetica-Oblique'
    )
    
    code_style = ParagraphStyle(
        'Code',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor("#000000"),
        backColor=colors.HexColor("#f0f0f0"),
        borderWidth=1,
        borderColor=colors.HexColor(C_GRAY),
        spaceAfter=10,
        fontName='Courier'
    )
    
    # Title Page
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph("RED TONGUE REFACTORY", title_style))
    story.append(Paragraph("Version 4.0.0", subtitle_style))
    story.append(Paragraph("The Idiot's Guide", subtitle_style))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("By Joshua Alexander", body_style))
    story.append(Paragraph("August 28, 2026", body_style))
    story.append(PageBreak())
    
    # Table of Contents (simplified)
    story.append(Paragraph("TABLE OF CONTENTS", heading_style))
    story.append(Paragraph("1. What is RedTongue Refactory?", body_style))
    story.append(Paragraph("2. Installation & Setup", body_style))
    story.append(Paragraph("3. Main Interface Overview", body_style))
    story.append(Paragraph("4. The Five Decks", body_style))
    story.append(Paragraph("   - Focus Studio", body_style))
    story.append(Paragraph("   - Ripper (Media Downloader)", body_style))
    story.append(Paragraph("   - Alchemist (Code Transformer)", body_style))
    story.append(Paragraph("   - Crucible (Testing Environment)", body_style))
    story.append(Paragraph("   - PyLib (Library Manager)", body_style))
    story.append(Paragraph("5. AI Agent System", body_style))
    story.append(Paragraph("6. ToolLayer Commands", body_style))
    story.append(Paragraph("7. Legal & License", body_style))
    story.append(PageBreak())
    
    # Chapter 1
    story.append(Paragraph("1. WHAT IS RED TONGUE REFACTORY?", heading_style))
    story.append(Paragraph(
        "RedTongue Refactory is an advanced AI-powered development environment designed to help you write, "
        "refactor, test, and manage code with intelligent assistance. Think of it as having a team of expert "
        "programmers working alongside you.",
        body_style
    ))
    story.append(Paragraph(
        "<b>Key Features:</b>",
        body_style
    ))
    story.append(Paragraph(
        "• <b>AI Agents:</b> Smart assistants that understand your code and can suggest improvements, fix bugs, "
        "or explain complex sections.<br/>"
        "• <b>ToolLayer:</b> A powerful set of commands that let the AI interact with your files, run shell "
        "commands, install packages, and more.<br/>"
        "• <b>Five Specialized Decks:</b> Different workspaces optimized for specific tasks like coding, "
        "downloading media, testing, and managing libraries.<br/>"
        "• <b>RAG System:</b> Retrieval-Augmented Generation that helps the AI understand your entire codebase "
        "by indexing and searching through your files.",
        body_style
    ))
    story.append(Spacer(1, 0.3*inch))
    
    # Chapter 2
    story.append(Paragraph("2. INSTALLATION & SETUP", heading_style))
    story.append(Paragraph("<b>Requirements:</b>", body_style))
    story.append(Paragraph(
        "• Python 3.8 or higher<br/>"
        "• pip (Python package manager)<br/>"
        "• Git (optional, for version control features)",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Step 1: Install Dependencies</b>", body_style))
    story.append(Paragraph(
        "Open your terminal or command prompt and run:",
        body_style
    ))
    story.append(Paragraph(
        "pip install PyQt6 sentence-transformers yt_dlp aiohttp requests gitpython",
        code_style
    ))
    story.append(Paragraph(
        "<i>Note: yt_dlp is optional and only needed if you plan to use the Ripper deck for downloading media.</i>",
        note_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Step 2: Configure API Keys</b>", body_style))
    story.append(Paragraph(
        "Create a config.json file in the project directory with your API keys:",
        body_style
    ))
    story.append(Paragraph(
        '{\n  "api_key": "your-openai-api-key-here",\n  "model": "gpt-4"\n}',
        code_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Step 3: Run the Application</b>", body_style))
    story.append(Paragraph(
        "python main.py",
        code_style
    ))
    story.append(PageBreak())
    
    # Chapter 3
    story.append(Paragraph("3. MAIN INTERFACE OVERVIEW", heading_style))
    story.append(Paragraph(
        "When you launch RedTongue Refactory, you'll see a sleek, dark-themed interface divided into several sections:",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Left Panel - File Explorer:</b>", body_style))
    story.append(Paragraph(
        "Browse your project files in a tree view. Click on any file to open it in the editor.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Center Panel - Code Editor:</b>", body_style))
    story.append(Paragraph(
        "Edit your code with syntax highlighting. The editor supports multiple file types and provides "
        "real-time feedback on syntax errors.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Right Panel - AI Chat:</b>", body_style))
    story.append(Paragraph(
        "Interact with the AI agents here. Type your questions or commands, and the AI will respond with "
        "suggestions, explanations, or execute tools on your behalf.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Bottom Panel - Console/Output:</b>", body_style))
    story.append(Paragraph(
        "View the output of executed commands, tool results, and system messages.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Top Menu - Deck Launcher:</b>", body_style))
    story.append(Paragraph(
        "Access the five specialized decks: Focus Studio, Ripper, Alchemist, Crucible, and PyLib.",
        body_style
    ))
    story.append(PageBreak())
    
    # Chapter 4
    story.append(Paragraph("4. THE FIVE DECKS", heading_style))
    
    story.append(Paragraph("4.1 Focus Studio", heading_style))
    story.append(Paragraph(
        "Your primary coding environment. Use Focus Studio for:",
        body_style
    ))
    story.append(Paragraph(
        "• Writing and editing code<br/>"
        "• Getting AI-assisted refactoring suggestions<br/>"
        "• Running linters and formatters<br/>"
        "• Managing project structure",
        body_style
    ))
    story.append(Paragraph(
        "<i>Tip: Use Ctrl+Enter to send your current selection to the AI for quick analysis.</i>",
        note_style
    ))
    story.append(Spacer(1, 0.3*inch))
    
    story.append(Paragraph("4.2 Ripper (Media Downloader)", heading_style))
    story.append(Paragraph(
        "Download audio and video content from over 100 supported websites including YouTube, Vimeo, "
        "SoundCloud, and more.",
        body_style
    ))
    story.append(Paragraph(
        "<b>How to use:</b>",
        body_style
    ))
    story.append(Paragraph(
        "1. Paste the URL of the video/audio you want to download<br/>"
        "2. Choose your preferred format (MP4, MP3, WAV, etc.)<br/>"
        "3. Select quality settings<br/>"
        "4. Click Download",
        body_style
    ))
    story.append(Paragraph(
        "<b>LEGAL NOTICE:</b> This tool is NOT intended for downloading copyrighted materials. Only download "
        "content you have the right to access or that is available under appropriate licenses (Creative Commons, "
        "public domain, etc.). You are solely responsible for complying with copyright laws.",
        note_style
    ))
    story.append(Spacer(1, 0.3*inch))
    
    story.append(Paragraph("4.3 Alchemist (Code Transformer)", heading_style))
    story.append(Paragraph(
        "Transform code between languages, frameworks, or paradigms. The Alchemist can:",
        body_style
    ))
    story.append(Paragraph(
        "• Convert Python to JavaScript (and vice versa)<br/>"
        "• Migrate code between framework versions<br/>"
        "• Refactor code to follow design patterns<br/>"
        "• Optimize performance-critical sections",
        body_style
    ))
    story.append(Spacer(1, 0.3*inch))
    
    story.append(Paragraph("4.4 Crucible (Testing Environment)", heading_style))
    story.append(Paragraph(
        "Run tests, benchmarks, and validations in an isolated environment.",
        body_style
    ))
    story.append(Paragraph(
        "• Execute unit tests with detailed reports<br/>"
        "• Run performance benchmarks<br/>"
        "• Validate code against coding standards<br/>"
        "• Debug issues with step-through execution",
        body_style
    ))
    story.append(Spacer(1, 0.3*inch))
    
    story.append(Paragraph("4.5 PyLib (Library Manager)", heading_style))
    story.append(Paragraph(
        "Manage Python packages and dependencies for your projects.",
        body_style
    ))
    story.append(Paragraph(
        "• Install, update, or remove packages<br/>"
        "• Create and manage virtual environments<br/>"
        "• Export requirements.txt files<br/>"
        "• Check for security vulnerabilities in dependencies",
        body_style
    ))
    story.append(PageBreak())
    
    # Chapter 5
    story.append(Paragraph("5. AI AGENT SYSTEM", heading_style))
    story.append(Paragraph(
        "RedTongue uses a sophisticated multi-agent system to assist you:",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>AgentSwarm:</b>", body_style))
    story.append(Paragraph(
        "Coordinates multiple AI agents working together on complex tasks. When you ask a question, "
        "the Swarm determines which agent is best suited to answer.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>FailoverStack:</b>", body_style))
    story.append(Paragraph(
        "Ensures reliability by automatically switching to backup models or strategies if the primary "
        "agent fails or times out.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>RAG (Retrieval-Augmented Generation):</b>", body_style))
    story.append(Paragraph(
        "Indexes your codebase to provide contextually relevant answers. Instead of generic responses, "
        "the AI can reference your actual code, variable names, and project structure.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>DiagnosticBrain:</b>", body_style))
    story.append(Paragraph(
        "Specializes in identifying bugs, performance issues, and security vulnerabilities. It analyzes "
        "error messages and stack traces to provide targeted solutions.",
        body_style
    ))
    story.append(PageBreak())
    
    # Chapter 6
    story.append(Paragraph("6. TOOLLAYER COMMANDS", heading_style))
    story.append(Paragraph(
        "The ToolLayer provides the AI with capabilities to interact with your system. Here are the key commands:",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>File Operations:</b>", body_style))
    story.append(Paragraph(
        "• <b>read_file(path)</b> - Read contents of a file<br/>"
        "• <b>write_file(path, content)</b> - Write content to a file<br/>"
        "• <b>list_files(directory)</b> - List files in a directory<br/>"
        "• <b>search_files(pattern, directory)</b> - Search for files matching a pattern",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>Code Analysis:</b>", body_style))
    story.append(Paragraph(
        "• <b>analyze_code(file_path)</b> - Analyze code for issues<br/>"
        "• <b>get_imports(file_path)</b> - Extract import statements<br/>"
        "• <b>find_symbol(symbol_name)</b> - Find where a symbol is defined<br/>"
        "• <b>lint_file(file_path)</b> - Run linter on a file",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>System Operations:</b>", body_style))
    story.append(Paragraph(
        "• <b>run_shell(command)</b> - Execute shell commands<br/>"
        "• <b>install_package(package_name)</b> - Install Python packages<br/>"
        "• <b>git_status()</b> - Check Git repository status<br/>"
        "• <b>get_system_info()</b> - Get system information",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("<b>RAG Operations:</b>", body_style))
    story.append(Paragraph(
        "• <b>index_project()</b> - Index the entire project for RAG<br/>"
        "• <b>query_rag(question)</b> - Ask questions about indexed code<br/>"
        "• <b>rebuild_index()</b> - Rebuild the RAG index from scratch",
        body_style
    ))
    story.append(PageBreak())
    
    # Chapter 7
    story.append(Paragraph("7. LEGAL & LICENSE", heading_style))
    story.append(Paragraph(
        "<b>Proprietary License:</b>",
        body_style
    ))
    story.append(Paragraph(
        "RedTongue Refactory is NOT free software. It is the exclusive intellectual property of "
        "Joshua Alexander. All rights reserved.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(
        "You may NOT copy, distribute, sell, sublicense, or transfer this software without explicit "
        "written permission. You may NOT reverse engineer, decompile, or disassemble the software.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(
        "<b>External Dependencies:</b><br/>"
        "This software uses external libraries (yt_dlp, PyQt6, sentence-transformers, etc.) which remain "
        "the property of their respective owners and are subject to their own licenses.",
        body_style
    ))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph(
        "<b>Contact for Licensing:</b><br/>"
        "Name: Joshua Alexander<br/>"
        "Email: somebodysomeone1982@gmail.com<br/>"
        "GitHub: Taterfacer<br/>"
        "Patreon: patreon.com/taterfacer",
        body_style
    ))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph(
        "© 2026 Joshua Alexander. All Rights Reserved.",
        body_style
    ))
    
    # Build PDF
    doc.build(story)
    print(f"✓ PDF generated successfully: {output_path}")

if __name__ == "__main__":
    generate_pdf()
