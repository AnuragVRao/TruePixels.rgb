import React from 'react';

/**
 * The signed-out start page: the project title and its credits. The entry
 * points (Admin Login, Sign In, Create Account) are in the header; the
 * copyright line is in Layout's footer. Plain, in the Purple group (DBIM §2).
 */
const CONTRIBUTORS = [
  { name: 'Amogh R Gowda', roll: '241IT008' },
  { name: 'Anurag V Rao', roll: '241IT011' },
  { name: 'Debanshu Mitra', roll: '241IT019' },
];

export const LandingPage: React.FC = () => (
  <>
    <div className="min-h-[calc(100vh-14rem)] flex flex-col items-center justify-center text-center">
      <h1 className="text-4xl font-bold text-primary">
        TruePixels.rgb
      </h1>
      <p className="mt-2 text-2xl font-semibold text-foreground">AI Image Detection System</p>
      <p className="mt-3 text-base text-muted-foreground">Carried out as part of the Software Engineering Project</p>
      <div className="mt-4 h-1 w-20 rounded-full bg-gradient-to-r from-primary to-secondary" />

      <h2 className="mt-12 text-xl font-semibold text-primary">Team Members</h2>
      <ul className="mt-2 space-y-1.5 text-base text-foreground">
        {CONTRIBUTORS.map((c) => (
          <li key={c.roll}>{c.name} - {c.roll}</li>
        ))}
      </ul>

      <h2 className="mt-10 text-xl font-semibold text-primary">Under the guidance of Course Instructor</h2>
      <p className="mt-2 text-base text-foreground">Prof. Jaidhar C D</p>
    </div>
  </>
);
