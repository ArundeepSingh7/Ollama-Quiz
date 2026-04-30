# 📚 QuizAI API

QuizAI API is a backend service that generates quiz questions from uploaded documents (PDF and Word) using a locally hosted large language model via Ollama.

The system extracts text from documents, processes it in chunks, and generates structured quiz questions such as multiple choice and true/false in a scalable and efficient way.

---

## ⚙️ How It Works

1. Upload a document (PDF / DOCX)
2. Text is extracted using parsing libraries
3. Content is split into chunks for better LLM performance
4. Each chunk is sent to a local Ollama model (e.g. Mistral)
5. Responses are parsed into structured quiz format

---

## 🚀 Key Features

* Local LLM usage (no external API dependency)
* Supports PDF and Word documents
* Chunk-based processing for large files
* Async + streaming quiz generation
* Duplicate question filtering
* Token budget optimization

---

## 📦 Requirements

```txt
fastapi
uvicorn
requests
httpx
python-multipart
PyMuPDF
pdfplumber
python-docx
anyio
pydantic
```

Install with:

```bash
pip install -r requirements.txt
```

---

## 🧠 Model & Runtime Requirements

This project depends on **Ollama** for running local LLMs.

### Install Ollama:

https://ollama.com

### Run Ollama server:

```bash
ollama serve
```

### Pull model (example: Mistral):

```bash
ollama pull mistral
```

---

## 📄 License Information

### This Project

You can choose your own license for this codebase (e.g. MIT).

---

### Ollama

Ollama is a separate dependency and is governed by its own license:

* https://ollama.com/license

---

### Mistral Model

The `mistral` model provided via Ollama is subject to the **Mistral AI license**.

You must comply with:

* Mistral model usage terms
* Any restrictions on commercial usage (depending on version)

Official reference:

* https://mistral.ai/terms

---

## ⚠️ Important Notes

* This project does **not include or redistribute model weights**
* Models are pulled and run locally via Ollama
* You are responsible for complying with model licenses

---

## 👨‍💻 Author

Arundeep Singh
(e.g. GitHub profile or portfolio)

---
