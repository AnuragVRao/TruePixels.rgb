import React from 'react';

/**
 * The signed-out start page: the project title and its credits. The entry
 * points (Admin Login, Sign In, Create Account) are in the header; the
 * copyright line is in Layout's footer. Plain, in the Blue group (DBIM §2).
 * Sizes (.landing-* in index.css) are larger than the DBIM type scale on
 * purpose (owner's mock-up, 2026-10-12) and shrink with the window height so
 * the page fits without scrolling.
 */
const CONTRIBUTORS = [
  { name: 'Amogh R Gowda', roll: '241IT008' },
  { name: 'Anurag V Rao', roll: '241IT011' },
  { name: 'Debanshu Mitra', roll: '241IT019' },
];

export const LandingPage: React.FC = () => (
  <>
    <div className="landing min-h-[calc(100vh-17rem)] flex flex-col items-center justify-center text-center">
      <h1 className="landing-title font-bold text-primary">
        TruePixels.rgb
      </h1>
      <p className="mt-1 landing-subtitle font-semibold text-foreground">AI Image Detection System</p>
      <p className="mt-2 landing-body text-muted-foreground">Carried out as part of the Software Engineering Project</p>
      <div className="mt-4 h-1 w-28 rounded-full bg-gradient-to-r from-primary to-secondary" />

      <h2 className="landing-gap landing-heading font-bold text-primary">Team Members</h2>
      <ul className="mt-2 landing-body text-foreground">
        {CONTRIBUTORS.map((c) => (
          <li key={c.roll}>{c.name} - {c.roll}</li>
        ))}
      </ul>

      <h2 className="landing-gap landing-heading font-bold text-primary">Under the guidance of Course Instructor</h2>
      <p className="mt-2 landing-body text-foreground">Prof. Jaidhar C D</p>
    </div>
  </>
);
