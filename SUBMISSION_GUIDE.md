# Submission checklist and recording plan

## What to enter in the submission form

| Field | What to provide |
| --- | --- |
| Project Demo | Your reachable hosted interactive demo URL. If you do not host it, use a recorded walkthrough only if the submission rules permit. localhost links do not work on a judge's laptop. |
| Source Code | A public repository URL containing the clean source package and LAPTOP_SETUP.md. |
| Video | Your uploaded recording URL, for example an unlisted video or Loom recording that judges can open. |
| Other Link | A public link to the repository's LAPTOP_SETUP.md or a release containing the code ZIP. |
| Presentation | Upload submission/Trusted_Trade_Presentation.pdf, or the editable PPTX. Both are below the 20 MB limit. |
| Tech Challenge Participation | Select the Valio Aimo / Trusted Trade Agents challenge as named in the form. |

No repository, hosted public demo or uploaded video was created automatically.
Create the repository and record/upload the video before copying those URLs into
the form. Test each link in a private/incognito browser window. Keep any hosted
process running for the judging period. A recorded video remains useful if a
live service is slow or unavailable.

## Fast source-code publication

1. Extract this ZIP into a NEW clean folder. Do not upload your working folder
   containing keys, catalogue or purchase database.
2. Create a public repository in your own GitHub account. Upload the extracted
   source files, including LAPTOP_SETUP.md, requirements-lock.txt, launch scripts
   and the submission folder. You can use GitHub's Upload files flow or Git.
3. Confirm no config.env, real tokens, official catalogue or local database is
   present. .gitignore protects normal Git workflows but does not sanitize a
   manually selected upload or a file already tracked by Git.
4. Put the repository URL in Source Code. Point Other Link to LAPTOP_SETUP.md.

If you already have a public repository, update that repository rather than
creating another one. The sample demo is deliberately key-free. Live users need
their own authorised keys and the organiser-supplied catalogue. Do not promise
that the offline sample can interpret arbitrary dishes.

## Suggested three-minute recording

| Time | Screen and narration |
| --- | --- |
| 0:00–0:20 | Title and buyer request: spaghetti bolognese for 200 people. Explain the agent assembles an ingredient basket. |
| 0:20–1:05 | Show the seeded meal basket, checked quantities/products and missing-wine proposal. Accept the omission and show its mock receipt. |
| 1:05–1:40 | Open the 1,000 L milk request. Show €1,770 including tax against €1,200 authority, reviewer approval and fresh validation. |
| 1:40–2:05 | Show the 10 L milk mock receipt and explain that an eligible product request within authority needs no human spending approval. |
| 2:05–2:35 | Open the audit history and API docs. Explain that external agents use the same structured interface. |
| 2:35–3:00 | Show LAPTOP_SETUP.md, distinguish fixed offline samples from live Claude, and state that receipts are mock because the challenge has no supplier order API. |

The eight-slide deck has speaker notes and a separate Presentation_Script.md.
Use the deck for the pitch and the application for the recorded walkthrough.
When recording sample mode, leave the offline banner visible. Do not display
config.env, API keys, terminal credentials or real customer data in the video.

## Copyable project description

Trusted Trade turns kitchen requests into priced ingredient baskets through an
open purchasing API. Buyers can request a dish and headcount, compare catalogue
offers, review substitutions or omissions, and confirm an exact basket. The
gateway enforces spending authority, recorded product requirements and delivery
checks, then revalidates before saving a mock receipt. A readable audit trail
explains each decision. The submission includes a dashboard, voice integration,
an external agent client and a key-free laptop walkthrough with fixed samples.
Live recipe planning uses Claude and the supplied Aimo mock APIs.

## Last checks

- Open every submitted URL without relying on your signed-in session.
- Upload the PDF or PPTX, not the code ZIP, in the Presentation field.
- Use a valid delivery date for live requests. Sample dates are generated fresh.
- Clearly explain the distinction between spending approval and final mock
  commitment, and between catalogue claims and independently certified facts.
- Confirm the deadline and any event-specific video-length or team requirements.
