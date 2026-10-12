import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, Mail } from 'lucide-react';
import { CONTACT_EMAIL } from '../lib/contact';

/**
 * Frequently asked questions. Every figure here is the system's own
 * (CLAUDE.md §5-6, docs/how-a-score-is-computed.md); update them together.
 * Public: no sign-in needed.
 */
const FAQS: { q: string; a: React.ReactNode }[] = [
  {
    q: 'What does TruePixels.rgb do?',
    a: (
      <p>
        It estimates whether an image was made by an AI image generator or is a real photograph. Two separate
        pretrained detectors read the same image: one looks at what the picture shows, the other at fine detail in
        the pixel grid. Their scores are combined into one verdict.
      </p>
    ),
  },
  {
    q: 'Which images can I check?',
    a: (
      <ul className="list-disc pl-5 space-y-1">
        <li>JPG or PNG files only. The file contents are checked, not just the name.</li>
        <li>At most 10 MB and at most 25 megapixels.</li>
        <li>Both sides at least 64 pixels.</li>
      </ul>
    ),
  },
  {
    q: 'How is the verdict decided?',
    a: (
      <>
        <p>
          The content detector (Community Forensics) and the frequency detector (SPAI) each give a score between 0
          and 1, where higher means more likely AI. The combined score is 0.55 × content + 0.45 × frequency.
        </p>
        <p>The image is marked <strong>AI Generated</strong> if the combined score is 0.4524 or more, otherwise <strong>Real</strong>.</p>
      </>
    ),
  },
  {
    q: 'What does the confidence percentage mean?',
    a: (
      <>
        <p>
          It shows how far the combined score is from the dividing line, in favour of the verdict shown. It is 50 %
          exactly at the line and rises to 100 % at the far end, so it is never below 50 %.
        </p>
        <p>High is 85 % or more, Moderate 65–85 %, Low under 65 %. It is a margin, not a calibrated probability.</p>
      </>
    ),
  },
  {
    q: 'How accurate is it?',
    a: (
      <>
        <p>On images that played no part in setting it up, it separated:</p>
        <ul className="list-disc pl-5 space-y-1">
          <li>images from 19 generators released in 2025 from matching real photos with 79.8 % accuracy;</li>
          <li>images from 2022–23 generators from camera photos with 93.9 % accuracy.</li>
        </ul>
        <p>
          These figures describe those test images, not every image you might upload. Some recent generators are
          often missed (for example FLUX.2 and GPT-image-1), and newer generators have not been tested.
        </p>
      </>
    ),
  },
  {
    q: 'Why could a real photo be marked AI Generated?',
    a: (
      <p>
        Heavy processing can make real photos look generated. Phone camera enhancement and AI upscalers are common
        causes. Resizing an image also weakens the frequency detector. Where you can, check the original file
        straight from the camera.
      </p>
    ),
  },
  {
    q: 'Why does it say the frequency score was "not measured"?',
    a: (
      <p>
        The frequency detector reads 224 × 224 pixel patches. An image smaller than that on either side has no
        complete patch, so the verdict rests on the content detector alone. The result page says so when this
        happens.
      </p>
    ),
  },
  {
    q: 'What are the explanation panels?',
    a: (
      <p>
        They are optional pictures that show where each detector looked: an attention map from the content
        detector and a patch spectrum from the frequency detector. Asking for them adds roughly 1–4 seconds. The
        verdict is the same either way.
      </p>
    ),
  },
  {
    q: 'How long does an analysis take?',
    a: (
      <p>
        Usually 1–3 seconds for an ordinary photo. Very large images take longer, sometimes 30 seconds or more,
        because the frequency detector reads every patch at full resolution.
      </p>
    ),
  },
  {
    q: 'Can other users see my images or results?',
    a: (
      <p>
        No. Your scan history and results are filtered by your account, and other users cannot open them. You can
        download a PDF report of any result from its result page.
      </p>
    ),
  },
  {
    q: 'I forgot my password or did not get a code.',
    a: (
      <>
        <p>
          Use <Link to="/forgot-password" className="text-link underline">Forgot password</Link> on the sign-in page.
          We e-mail a 6-digit code that expires after a few minutes.
        </p>
        <p>
          Check your spam folder. You can ask for a new code at most once a minute, and a code stops working after 5
          wrong entries.
        </p>
      </>
    ),
  },
  {
    q: 'Is a result proof that an image is real or fake?',
    a: <p>No. A result is a model&apos;s estimate, not proof. Use it as one piece of evidence among others.</p>,
  },
];

export const FaqPage: React.FC = () => (
  <div className="max-w-3xl mx-auto space-y-6">
    <div className="space-y-2">
      <h1 className="text-3xl font-bold text-primary">Frequently asked questions</h1>
      <p className="text-sm text-muted-foreground">Select a question to see the answer.</p>
    </div>

    <div className="divide-y divide-border rounded-lg border border-border bg-card">
      {FAQS.map(({ q, a }) => (
        <details key={q} className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 sm:px-5 sm:py-4 text-base font-semibold text-foreground hover:bg-accent [&::-webkit-details-marker]:hidden">
            {q}
            <ChevronDown className="w-5 h-5 shrink-0 text-primary transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <div className="px-4 pb-4 sm:px-5 text-sm text-foreground space-y-2">{a}</div>
        </details>
      ))}
    </div>

    <section className="rounded-lg border border-border bg-accent p-5 space-y-2" aria-labelledby="contact-heading">
      <h2 id="contact-heading" className="text-xl font-bold text-primary">Still have a question?</h2>
      <p className="text-sm text-foreground">E-mail us at:</p>
      <a href={`mailto:${CONTACT_EMAIL}`} className="inline-flex items-center gap-2 text-base font-semibold text-link hover:underline break-all">
        <Mail className="w-5 h-5 shrink-0 text-primary" aria-hidden="true" /> {CONTACT_EMAIL}
      </a>
    </section>
  </div>
);
