---
layout: default
title: About Us
permalink: /about/
---
# About Us

<p class="about-intro">WCRS LP FM is Central Ohio's community radio station broadcasting on 92.7 and 98.3 FM in Franklin County. WCRS is a service of The Neighborhood Network and a Pacifica Affiliate airing Democracy Now!, and other syndicated public affairs programs in addition to locally made music, talk, and public affairs programs in English and Spanish.</p>

<section class="about-panel about-panel-cta">
  <h2>WCRS Needs You!</h2>
  <p>As Columbus Community Station, we are people driven &mdash; which in our case means we need people to drive this station. Right now we are looking for volunteers. If you are interested in volunteering, or if you are interested in producing a program, drop us a line below.</p>
  <p><a class="btn-accent" href="#contact">Contact us &rarr;</a></p>
</section>

<section class="about-panel about-panel-mission">
  <h2>Our Mission</h2>
  <p>WCRS-LP FM is a non-commercial, listener-supported community radio station serving Central Ohioans, providing quality programming to:</p>
  <ul class="mission-list">
    <li>Promote personal and civic responsibility, informed action and thoughtful living</li>
    <li>Challenge cultural and intellectual assumptions</li>
    <li>Celebrate local cultures</li>
    <li>Air alternative points of view and facilitate understanding through dialogue</li>
    <li>Provide media training and foster community empowerment and participation</li>
    <li>Provide representation for under-served and under-represented constituencies and viewpoints, and provide news and information not commonly found elsewhere on the airwaves</li>
  </ul>
</section>

<section class="contact-section" id="contact">
  <h2>Contact Us</h2>
  <p class="contact-intro">Have a question? Interested in volunteering or producing a program? Drop us a line below.</p>
  <div class="contact-form-wrapper">
    <form id="contactForm" action="/contact.php" method="post" novalidate>
      <div class="hp-field" aria-hidden="true">
        <label for="website">Website</label>
        <input type="text" id="website" name="website" tabindex="-1" autocomplete="off">
      </div>
      <input type="hidden" id="formLoadTime" name="load_time">
      <div class="form-row">
        <div class="form-group">
          <label for="contactName">Name <span class="required" aria-hidden="true">*</span></label>
          <input type="text" id="contactName" name="name" required maxlength="100" placeholder="Your name" autocomplete="name">
        </div>
        <div class="form-group">
          <label for="contactEmail">Email <span class="required" aria-hidden="true">*</span></label>
          <input type="email" id="contactEmail" name="email" required maxlength="200" placeholder="you@example.com" autocomplete="email">
        </div>
      </div>
      <div class="form-group">
        <label for="contactSubject">Subject</label>
        <input type="text" id="contactSubject" name="subject" maxlength="200" placeholder="What's this about?">
      </div>
      <div class="form-group">
        <label for="contactMessage">Message <span class="required" aria-hidden="true">*</span></label>
        <textarea id="contactMessage" name="message" required maxlength="2000" rows="6" placeholder="Your message..." aria-describedby="charCount"></textarea>
        <div class="char-count"><span id="charCount">0</span> / 2000</div>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn-contact" id="contactSubmitBtn">Send Message</button>
      </div>
    </form>
  </div>

  <dialog id="contactModal" class="contact-modal" role="alertdialog"
          aria-labelledby="contactModalTitle" aria-describedby="contactModalMsg">
    <h3 id="contactModalTitle" class="contact-modal-title">Message sent</h3>
    <p id="contactModalMsg" class="contact-modal-msg"></p>
    <div class="contact-modal-actions">
      <button type="button" class="btn-contact" id="contactModalDismiss" autofocus>OK</button>
    </div>
  </dialog>
</section>
