import React from 'react';

/**
 * The signed-out start page: the project title and its credits. The entry
 * points (Admin Login, Sign In, Create Account) are in the header; the
 * copyright line is in Layout's footer.
 */
const CONTRIBUTORS = [
  { name: 'Amogh R Gowda', roll: '241IT008' },
  { name: 'Anurag V Rao', roll: '241IT011' },
  { name: 'Debanshu Mitra', roll: '241IT019' },
];

export const LandingPage: React.FC = () => (
  <>
    {/* Background glows, fixed to the viewport and behind everything but the page background. */}
    <div className="fixed inset-0 z-0 pointer-events-none overflow-hidden" aria-hidden="true">
      <div className="absolute -top-48 -left-48 w-[36rem] h-[36rem] rounded-full bg-primary/30 blur-[120px]" />
      <div className="absolute -bottom-56 -right-40 w-[40rem] h-[40rem] rounded-full bg-secondary/25 blur-[120px]" />
      <div className="absolute -bottom-72 -right-72 w-[36rem] h-[36rem] rounded-full border border-primary/30" />
    </div>

    <div className="relative z-10 min-h-[calc(100vh-12rem)] flex flex-col items-center justify-center text-center">
      <h1 className="text-5xl sm:text-7xl font-extrabold tracking-tight pb-2 bg-gradient-to-r from-foreground from-30% via-primary to-secondary bg-clip-text text-transparent">
        TruePixels.rgb
      </h1>
      <p className="mt-2 text-xl sm:text-3xl font-semibold text-foreground">AI Image Detection System</p>
      <p className="mt-3 text-base sm:text-xl text-foreground/80">Carried out as part of the Software Engineering Project</p>
      <div className="mt-4 h-0.5 w-20 rounded-full bg-gradient-to-r from-primary to-secondary" />

      <h2 className="mt-12 text-lg sm:text-xl font-semibold text-primary">Team Members</h2>
      <ul className="mt-2 space-y-1.5 text-base sm:text-lg text-foreground">
        {CONTRIBUTORS.map((c) => (
          <li key={c.roll}>{c.name} - {c.roll}</li>
        ))}
      </ul>

      <h2 className="mt-10 text-lg sm:text-xl font-semibold text-primary">Under the guidance of Course Instructor</h2>
      <p className="mt-2 text-base sm:text-lg text-foreground">Prof. Jaidhar C D</p>
    </div>
  </>
);
