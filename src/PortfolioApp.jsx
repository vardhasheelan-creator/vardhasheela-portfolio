import React from "react";

export default function PortfolioApp() {
  return (
    <div className="min-h-screen bg-neutral-900 text-slate-100 antialiased">
      <style>{`
        /* Neon glow and card animations */
        .shadow-neon {
          box-shadow: 0 8px 18px rgba(0,0,0,0.6);
          transition: transform .35s cubic-bezier(.2,.9,.2,1), box-shadow .35s ease, filter .35s ease;
        }
        .shadow-neon:hover {
          transform: translateY(-8px) scale(1.02);
          box-shadow: 0 18px 40px rgba(99,102,241,0.12), 0 0 30px rgba(99,102,241,0.06);
          filter: saturate(1.05) drop-shadow(0 8px 18px rgba(99,102,241,0.08));
        }
        .neon-border {
          transition: box-shadow .35s ease, transform .35s ease;
        }
        .neon-border:hover {
          box-shadow: 0 6px 28px rgba(99,102,241,0.12), 0 0 18px rgba(255,105,180,0.06);
        }

        /* Ensure inputs and placeholders are high-contrast white */
        input, textarea {
          color: #ffffff !important;
        }
        input::placeholder, textarea::placeholder {
          color: rgba(255,255,255,0.75) !important; /* visible, but slightly muted */
          opacity: 1 !important;
        }

        /* reduce motion preference */
        @media (prefers-reduced-motion: reduce) {
          .shadow-neon, .neon-border {
            transition: none !important;
            transform: none !important;
          }
        }
      `}</style>

      {/* Header */}
      <header className="bg-black shadow-lg sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-full bg-gradient-to-br from-indigo-500 to-pink-500 flex items-center justify-center text-white font-semibold">V</div>
            <div>
              <div className="font-semibold">Vardhasheela N</div>
              <div className="text-xs text-slate-500">Consultation & Customer Service Training • Freelance Video Editor</div>
            </div>
          </div>

          <nav className="hidden md:flex gap-6 text-sm text-slate-300">
            <a href="#home" className="hover:text-slate-100">Home</a>
            <a href="#about" className="hover:text-slate-100">About</a>
            <a href="#services" className="hover:text-slate-100">Services</a>
            <a href="#portfolio" className="hover:text-slate-100">Work</a>
            <a href="#contact" className="hover:text-slate-100">Contact</a>
          </nav>

          <div className="flex items-center gap-3">
            <a href="#contact" className="hidden md:inline-block bg-indigo-600 text-white px-4 py-2 rounded-md text-sm">Hire Me</a>
            <button className="md:hidden p-2 bg-slate-100 rounded-md">Menu</button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <main className="max-w-6xl mx-auto px-6 py-12" id="home">
        <section className="grid grid-cols-1 md:grid-cols-2 gap-10 items-center">
          <div>
            <h1 className="text-3xl md:text-4xl font-extrabold leading-tight">
              Consultation & Customer Service Training for Individuals & Startups
              <span className="block text-indigo-600">&nbsp;|&nbsp; Freelance Video Editor</span>
            </h1>
            <p className="mt-4 text-slate-300 max-w-xl">
              I help individuals and early-stage teams improve customer conversations, build confident frontline staff,
              and tell better stories through clean, engaging video edits. Combine training, operational templates, and creative content to scale your brand.
            </p>

            <div className="mt-6 flex gap-3">
              <a href="#contact" className="bg-indigo-600 text-white px-4 py-2 rounded-md shadow">Book a Consultation</a>
              <a href="#portfolio" className="border border-slate-200 px-4 py-2 rounded-md text-slate-200">View Work</a>
            </div>

            <div className="mt-8 text-sm text-slate-500">
              <strong>Quick availability:</strong> Weekends and evenings for freelance editing. Training sessions by appointment.
            </div>
          </div>

          <div className="flex justify-center md:justify-end">
            {/* IMPORTANT: filename & casing must exactly match the file in public/assets on the server */}
            <img
              src="/assets/vardhasheela.jpeg"
              alt="Vardhasheela"
              className="w-72 h-72 rounded-xl object-cover shadow-lg border-2 border-pink-500/40"
            />
          </div>
        </section>

        {/* Services */}
        <section id="services" className="mt-16">
          <h2 className="text-2xl font-bold">What I Do</h2>
          <p className="mt-2 text-slate-300 max-w-2xl">Focused services designed for creators and small teams.</p>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-neutral-800 p-6 rounded-lg shadow-sm">
              <div className="text-indigo-600 font-semibold">Video Editing</div>
              <h3 className="mt-2 font-bold">Reels, Shorts & Client Edits</h3>
              <p className="mt-2 text-slate-300 text-sm">Short-form edits, YouTube shorts, corporate promos, travel & lifestyle edits.</p>
              <ul className="mt-3 text-sm text-slate-300 space-y-1">
                <li>• Reels & Shorts</li>
                <li>• Before / After edit samples</li>
                <li>• Captions & thumbnails (optional)</li>
              </ul>
            </div>

            <div className="bg-neutral-800 p-6 rounded-lg shadow-sm">
              <div className="text-indigo-600 font-semibold">Consultation</div>
              <h3 className="mt-2 font-bold">Customer Service Training</h3>
              <p className="mt-2 text-slate-300 text-sm">Training for startups and individuals on customer interaction, email drafting, escalation handling and soft skills.</p>
            </div>

            <div className="bg-neutral-800 p-6 rounded-lg shadow-sm">
              <div className="text-indigo-600 font-semibold">Cabin Crew Consultation</div>
              <h3 className="mt-2 font-bold">Interview & Grooming Prep</h3>
              <p className="mt-2 text-slate-300 text-sm">Interview prep, grooming tips, mock rounds, and practical advice for freshers.</p>
            </div>
          </div>
        </section>

        {/* Portfolio */}
        <section id="portfolio" className="mt-16">
          <h2 className="text-2xl font-bold">Selected Work</h2>
          <p className="mt-2 text-slate-300">A few recent edits and consultation snapshots.</p>

          <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-2 gap-6">
            {/* Use iframe (video) or replace with <img src="/assets/documentary.png" /> if you want thumbnails */}
            <div className="bg-neutral-800 rounded-lg overflow-hidden shadow-neon neon-border border-2 border-indigo-400/30">
              <div className="aspect-video">
                <iframe src="https://player.vimeo.com/video/1145647871" title="English Cashcow Edit" frameBorder="0" allow="autoplay; fullscreen; picture-in-picture" allowFullScreen className="w-full h-full"></iframe>
              </div>
              <div className="p-4">
                <div className="font-semibold">English Cashcow Edit</div>
                <div className="text-sm text-slate-300 mt-2">Short-form monetizable edit optimised for hooks and retention.</div>
              </div>
            </div>

            <div className="bg-neutral-800 rounded-lg overflow-hidden shadow-neon neon-border border-2 border-pink-400/30">
              <div className="aspect-video">
                <iframe src="https://player.vimeo.com/video/1145652720" title="Tamil Cashcow Edit" frameBorder="0" allow="autoplay; fullscreen; picture-in-picture" allowFullScreen className="w-full h-full"></iframe>
              </div>
              <div className="p-4">
                <div className="font-semibold">Tamil Cashcow Edit</div>
                <div className="text-sm text-slate-300 mt-2">Regional short-form edit showcasing localisation and pacing for Tamil audiences.</div>
              </div>
            </div>
          </div>
        </section>

        {/* About with timeline */}
        <section id="about" className="mt-16">
          <h2 className="text-2xl font-bold">About Me</h2>
          <p className="mt-2 text-slate-300 max-w-2xl">From cabin crew to instructor to technical support & freelance editor.</p>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="md:col-span-2 bg-neutral-800 p-6 rounded-lg shadow-sm">
              <h3 className="font-bold">My Journey</h3>
              <p className="mt-3 text-slate-300">I began my career as cabin crew, later worked as an instructor, and transitioned into technical support while freelancing as a video editor.</p>

              <div className="mt-6">
                <div className="space-y-4">
                  <TimelineItem year="2016" title="Cabin Crew" detail="Worked as cabin crew handling passenger safety & service." />
                  <TimelineItem year="2018" title="Cabin Crew Instructor" detail="Trained new recruits on grooming, safety and interviews." />
                  <TimelineItem year="2019" title="Freelance Video Editor" detail="Started freelance editing and content creation." />
                  <TimelineItem year="2023" title="Technical Support Engineer" detail="Working in L1/L2 support; handling tickets and customer communication." />
                </div>
              </div>
            </div>

            <aside className="bg-neutral-800 p-6 rounded-lg shadow-sm">
              <h4 className="font-bold">Skills</h4>
              <ul className="mt-3 text-sm text-slate-300 space-y-2">
                <li>• Video Editing (Reels, Shorts, Corporate)</li>
                <li>• Customer Service Training</li>
                <li>• Email Templates & SOPs</li>
              </ul>
            </aside>
          </div>
        </section>

        {/* Contact */}
        <section id="contact" className="mt-16 mb-20">
          <h2 className="text-2xl font-bold">Contact</h2>
          <p className="mt-2 text-slate-300">Work inquiries, training bookings, or a quick hello — drop a message.</p>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
            <form className="bg-neutral-800 p-6 rounded-lg shadow-sm">
              <label className="block text-sm font-medium text-slate-400">Name</label>
              <input className="mt-1 w-full border border-slate-700 rounded px-3 py-2 bg-neutral-800" placeholder="Your name" />

              <label className="block text-sm font-medium text-slate-400 mt-4">Email</label>
              <input className="mt-1 w-full border border-slate-700 rounded px-3 py-2 bg-neutral-800" placeholder="you@example.com" />

              <label className="block text-sm font-medium text-slate-400 mt-4">Message</label>
              <textarea className="mt-1 w-full border border-slate-700 rounded px-3 py-2 bg-neutral-800" rows={4} placeholder="Tell me about your project"></textarea>

              <div className="mt-4 flex items-center gap-3">
                <button className="bg-indigo-600 text-white px-4 py-2 rounded-md">Send Message</button>
                <a className="text-sm text-slate-400">Or message on WhatsApp</a>
              </div>
            </form>

            <aside className="bg-neutral-800 p-6 rounded-lg shadow-sm">
              <h4 className="font-bold">Contact Info</h4>
              <div className="mt-3 text-sm text-slate-300">
                <div>📍 Bengaluru, India</div>
                <div className="mt-2">✉️ vardhasheelan@gmail.com</div>
                <div className="mt-2">📞 +91 9113259228</div>
              </div>
            </aside>
          </div>
        </section>
      </main>

      <footer className="bg-black border-t py-6">
        <div className="max-w-6xl mx-auto px-6 text-sm text-slate-500">© {new Date().getFullYear()} Vardhasheela N • Built with care.</div>
      </footer>
    </div>
  );
}

function TimelineItem({ year, title, detail }) {
  return (
    <div className="flex items-start gap-4">
      <div className="text-xs text-slate-400 w-16 font-mono">{year}</div>
      <div>
        <div className="font-semibold">{title}</div>
        <div className="text-sm text-slate-300">{detail}</div>
      </div>
    </div>
  );
}
