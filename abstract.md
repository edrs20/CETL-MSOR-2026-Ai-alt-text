# Abstract and Title Suggestions

## Abstract

The HELM (Helping Engineers Learn Mathematics) workbooks — 50 workbooks, 500+ HTML pages, 924 mathematical diagrams — had zero accessibility descriptions, yet UK law (WCAG 2.1 AA, Equality Act 2010) requires them. Manual authoring at this scale is not feasible.

This paper describes a pipeline using Google's gemma4 multimodal model, run locally via Ollama on a consumer GPU, to automatically generate alt text and long descriptions for every HELM image. Running locally sidesteps university IT policy barriers and unpredictable API costs. Structured JSON output and programmatic post-processing produce clean descriptions conforming to DIAGRAM Centre POET guidelines. Each description is flagged as AI-generated and linked to a per-page feedback form, creating a human-in-the-loop review system open to maths experts, accessibility specialists, and screen reader users.

The entire stack — Ollama, gemma4, Python, HELM — is free and open source, offering a reproducible model for institutions facing the same challenge.

## Suggested Titles

1. **From Zero to 924: Using Local AI to Make Mathematical Diagrams Accessible at Scale**
2. **Free, Local, and Compliant: Automating Accessibility Descriptions for the HELM Workbooks**
3. **No API Key Required: A Local LLM Pipeline for Accessible Maths Diagrams**
4. **Prompting for Accessibility: Auto-generating Alt Text and Long Descriptions for Engineering Mathematics**
5. **AI on Your Own GPU: A Human-in-the-Loop Approach to Accessible Mathematical Figures**
