/* Inicialización sincrónica — el DOM ya existe al llegar aquí */
(function initExternalPages() {
  /* ── Re-inicializar scripts que dependen del DOM de pages.html ── */

      /* 1. Marquee de reseñas */
      var REVIEWS_LANE1 = [
        { text: "¡FPS por las nubes! No volvería atrás.", author: "Ruben_FPS", game: "Valorant", color: "purple", init: "R" },
        { text: "200 → 340 FPS en CS2. Simplemente increíble.", author: "XdarkSh0t", game: "CS2", color: "cyan", init: "X" },
        { text: "El mejor dinero que he gastado en gaming.", author: "ProGamer99", game: "Fortnite", color: "pink", init: "P" },
        { text: "Cero lag, cero stutters. Perfecto.", author: "LauraGames", game: "Apex", color: "green", init: "L" },
        { text: "Mi PC viejo rinde como si fuera nuevo.", author: "MiguelTech", game: "LoL", color: "purple", init: "M" },
        { text: "Stream sin drops por primera vez 🎉", author: "StreamQueen", game: "Twitch", color: "pink", init: "S" },
        { text: "Input lag mínimo, mis reacciones mejoraron.", author: "Zer0Delay", game: "Valorant", color: "cyan", init: "Z" },
        { text: "Instalé en 10 min y ya notaba la diferencia.", author: "QuickSetup", game: "CS2", color: "green", init: "Q" },
        { text: "Anti-cheat safe 100%, probado en torneo.", author: "TourneyAce", game: "Fortnite", color: "purple", init: "T" },
        { text: "Mi GPU se calienta menos. Sorprendente.", author: "CoolSystem", game: "Warzone", color: "cyan", init: "C" },
        { text: "De 90 FPS inestables a 180 estables. WOW.", author: "NightFrag", game: "Apex", color: "pink", init: "N" },
        { text: "Soporte técnico respondió en minutos.", author: "HappyUser", game: "LoL", color: "green", init: "H" },
      ];
      var REVIEWS_LANE2 = [
        { text: "Jamás pensé que el software hiciera tanto.", author: "SkepticalG", game: "CS2", color: "cyan", init: "S" },
        { text: "Temps bajaron 15°C. La diferencia se nota.", author: "CoolFPS", game: "Warzone", color: "green", init: "C" },
        { text: "El restore funciona de maravilla si hay dudas.", author: "SafeGamer", game: "Valorant", color: "purple", init: "S" },
        { text: "Mi Intel i5 rinde como un i7 ahora.", author: "CPUWizard", game: "Apex", color: "pink", init: "C" },
        { text: "240 FPS constantes. Nunca tan suave.", author: "SilkySmooth", game: "CS2", color: "cyan", init: "S" },
        { text: "Recomendado por mi equipo completo.", author: "TeamCaptain", game: "Valorant", color: "purple", init: "T" },
        { text: "Sin microfreezes desde que lo instalé.", author: "NoFreeze_X", game: "Fortnite", color: "green", init: "N" },
        { text: "Precio justo por lo que ofrece. 10/10.", author: "ValueGamer", game: "LoL", color: "pink", init: "V" },
        { text: "Activé el plan pro y fue un antes y después.", author: "ProUpgrade", game: "Warzone", color: "cyan", init: "P" },
        { text: "FPS estables durante 5h de sesión. 🔥", author: "SessionKing", game: "Apex", color: "purple", init: "S" },
        { text: "RAM optimizada, todo va más fluido.", author: "RAMmaster", game: "CS2", color: "green", init: "R" },
        { text: "Lo usé el día del torneo y gané. ¡Gracias!", author: "WinnerGG", game: "Valorant", color: "pink", init: "W" },
      ];
      function buildReviewCard(r) {
        return '<div class="rmc rmc--' + r.color + '">'
          + '<div class="rmc-stars"><span>★</span><span>★</span><span>★</span><span>★</span><span>★</span></div>'
          + '<div class="rmc-text">"' + r.text + '"</div>'
          + '<div class="rmc-author">'
          + '<div class="rmc-avatar rmc--' + r.color + '" style="background:rgba(155,48,255,0.12)">' + r.init + '</div>'
          + '<div><div class="rmc-name">' + r.author + '</div><div class="rmc-game">' + r.game + '</div></div>'
          + '</div></div>';
      }
      function populateLane(id, data) {
        var lane = document.getElementById(id);
        if (!lane) return;
        var doubled = data.concat(data);
        lane.innerHTML = doubled.map(buildReviewCard).join('');
      }
      populateLane('rml-1', REVIEWS_LANE1);
      populateLane('rml-2', REVIEWS_LANE2);

      /* 2. Acordeón de testimonios */
      document.querySelectorAll('[data-testi]').forEach(function(item) {
        var header = item.querySelector('.testi-header');
        if (!header) return;
        header.addEventListener('click', function() {
          var isOpen = item.classList.contains('t-open');
          document.querySelectorAll('[data-testi]').forEach(function(i) { i.classList.remove('t-open'); });
          if (!isOpen) item.classList.add('t-open');
        });
      });

      /* 3. Barras de puntuación */
      var summaryBox = document.getElementById('reviews-summary-box');
      if (summaryBox) {
        var obs = new IntersectionObserver(function(entries) {
          entries.forEach(function(entry) {
            if (entry.isIntersecting) {
              entry.target.querySelectorAll('.rs-bar-fill').forEach(function(bar) {
                bar.style.width = bar.dataset.pct + '%';
              });
              obs.unobserve(entry.target);
            }
          });
        }, { threshold: 0.3 });
        obs.observe(summaryBox);
      }

      /* 4. GSAP hover en iconos de features (si GSAP ya cargó) */
      if (typeof gsap !== 'undefined') {
        document.querySelectorAll('.feat-icon-wrap').forEach(function(icon) {
          icon.parentElement.addEventListener('mouseenter', function() {
            gsap.to(icon, { rotation: 15, scale: 1.15, duration: 0.35, ease: 'power2.out' });
          });
          icon.parentElement.addEventListener('mouseleave', function() {
            gsap.to(icon, { rotation: 0, scale: 1, duration: 0.5, ease: 'elastic.out(1, 0.7)' });
          });
        });
        /* Plan card tilt hover */
        document.querySelectorAll('.plan-card').forEach(function(card) {
          card.addEventListener('mousemove', function(e) {
            var rect = card.getBoundingClientRect();
            var nx = (e.clientX - rect.left) / rect.width - 0.5;
            var ny = (e.clientY - rect.top) / rect.height - 0.5;
            gsap.to(card, { rotateY: nx * 6, rotateX: -ny * 4, duration: 0.4, ease: 'power2.out', transformPerspective: 800 });
          });
          card.addEventListener('mouseleave', function() {
            gsap.to(card, { rotateY: 0, rotateX: 0, duration: 0.6, ease: 'elastic.out(1, 0.7)' });
          });
        });
      }

})();

/* ══════════════════════════════════════════ */

// ══════════════════════════════════════════════════
 // CONFIG
 // ══════════════════════════════════════════════════
 const RENDER_URL = 'https://casttweaks.vercel.app';
 // Debe coincidir EXACTAMENTE con OWNER_SECRET en el servidor (variable de entorno)
 const OWNER_SECRET = 'CASTTWEAKS_SECRET_2024_DONT_SHARE';
 const PLANS = {
 basic: { name:'Basic', base:5, xpm:2, days:30, col:'#9b30ff', type:'Basic', devs:1 },
 pro: { name:'Pro', base:10, xpm:3.5, days:30, col:'#e040fb', type:'Pro', devs:3 },
 lifetime: { name:'Lifetime', base:39.99, xpm:0, days:36500, col:'#ff6d00', type:'Lifetime', devs:5 }
 };
 // Mapa explícito plan → license_type para evitar que un error de PLANS corrompa el tipo
 const LICENSE_TYPE_MAP = { basic: 'Basic', pro: 'Pro', lifetime: 'Lifetime' };
 let activePlan = null;
 let activeDiscount = { code: '', pct: 0 };
 // ══════════════════════════════════════════════════
 // HMAC-SHA256 (Web Crypto API — nativo en todos los navegadores modernos)
 // ══════════════════════════════════════════════════
 async function _hmacSign(fields) {
 const ts = Math.floor(Date.now() / 1000);
 const msg = [String(ts), ...fields.map(f => String(f ?? ''))].join(':');
 const key = await crypto.subtle.importKey(
 'raw',
 new TextEncoder().encode(OWNER_SECRET),
 { name: 'HMAC', hash: 'SHA-256' },
 false,
 ['sign']
 );
 const buf = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(msg));
 const sig = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2,'0')).join('');
 return { ts, sig };
 }
 // ══════════════════════════════════════════════════
 // GSAP SETUP
 // ══════════════════════════════════════════════════
 // Corregido: Se eliminan CustomEase y DrawSVGPlugin porque fallan por CDN (son premium de GSAP)
 gsap.registerPlugin(ScrollTrigger);
 const mm = gsap.matchMedia();
 // ──────────────── CURSOR ────────────────
 const dot = document.getElementById('cursor-dot');
 const ring = document.getElementById('cursor-ring');
 let mx=0, my=0, rx=0, ry=0;
 // Configurar el centrado inicial para que coincida con el ratón
 gsap.set('#cursor-dot, #cursor-ring', { xPercent: -50, yPercent: -50 });
 window.addEventListener('mousemove', e => {
 mx = e.clientX; my = e.clientY;
 gsap.to(dot, { x: mx, y: my, duration: 0.08, ease: 'none' });
 });
 const xTo = gsap.quickTo(ring, 'x', { duration: 0.4, ease: 'power3.out' });
 const yTo = gsap.quickTo(ring, 'y', { duration: 0.4, ease: 'power3.out' });
 window.addEventListener('mousemove', e => { xTo(e.clientX); yTo(e.clientY); });
 document.querySelectorAll('a, button, .faq-q, .dpr').forEach(el => {
 el.addEventListener('mouseenter', () => {
 gsap.to(dot, { scale: 2.5, background: '#e040fb', duration: 0.2 });
 gsap.to(ring, { scale: 1.5, borderColor: 'rgba(224,64,251,0.6)', duration: 0.3 });
 });
 el.addEventListener('mouseleave', () => {
 gsap.to(dot, { scale: 1, background: '#e040fb', duration: 0.2 });
 gsap.to(ring, { scale: 1, borderColor: 'rgba(155,48,255,0.6)', duration: 0.3 });
 });
 });
 // ──────────────── CANVAS BACKGROUND ────────────────
 (function initCanvas() {
 const c = document.getElementById('bg-canvas');
 const ctx = c.getContext('2d');
 let W, H;
 function resize() { W = c.width = window.innerWidth; H = c.height = window.innerHeight; }
 resize(); window.addEventListener('resize', resize);
 const clamp = gsap.utils.clamp;
 const random = gsap.utils.random;
 const particles = Array.from({ length: 70 }, () => ({
 x: random(0, 1920), y: random(0, 1080),
 vx: random(-0.3, 0.3), vy: random(-0.3, 0.3),
 r: random(0.5, 2),
 a: random(0.15, 0.6),
 col: Math.random() > 0.5 ? '155,48,255' : '224,64,251'
 }));
 function draw() {
 ctx.clearRect(0, 0, W, H);
 particles.forEach(p => {
 p.x += p.vx; p.y += p.vy;
 if (p.x < 0) p.x = W; if (p.x > W) p.x = 0;
 if (p.y < 0) p.y = H; if (p.y > H) p.y = 0;
 ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
 ctx.fillStyle = `rgba(${p.col},${p.a})`; ctx.fill();
 });
 for (let i = 0; i < particles.length; i++) {
 for (let j = i + 1; j < particles.length; j++) {
 const dx = particles[i].x - particles[j].x, dy = particles[i].y - particles[j].y;
 const d = Math.sqrt(dx * dx + dy * dy);
 if (d < 120) {
 ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y);
 ctx.lineTo(particles[j].x, particles[j].y);
 ctx.strokeStyle = `rgba(155,48,255,${(1 - d / 120) * 0.12})`;
 ctx.lineWidth = 0.5; ctx.stroke();
 }
 }
 }
 requestAnimationFrame(draw);
 }
 draw();
 })();
 // ──────────────── HEADER SCROLL ────────────────
 ScrollTrigger.create({
 start: 'top -80px',
 onToggle: self => {
 gsap.to('#header', {
 borderBottomColor: self.isActive ? 'rgba(155,48,255,0.4)' : 'rgba(155,48,255,0.2)',
 duration: 0.4
 });
 }
 });
 // ──────────────── HERO ENTRANCE ────────────────
 mm.add('(prefers-reduced-motion: no-preference)', () => {
 const heroTl = gsap.timeline({ defaults: { ease: 'elastic.out(1, 0.7)', 'will-change': 'transform, opacity' } });
 heroTl.to('.hero-tag', { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }, 0.2)
 .from('#hero-title .line1', { y: 80, opacity: 0, duration: 0.9, ease: 'power4.out' }, 0.4)
 .from('#hero-title .line2', { y: 80, opacity: 0, duration: 0.9, ease: 'power4.out' }, 0.55)
 .to('#hero-desc', { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }, 0.7)
 .to('#hero-btns', { opacity: 1, duration: 0.6 }, 0.85)
 .from('#hero-btns .btn', { x: -30, opacity: 0, stagger: 0.12, duration: 0.6, ease: 'power3.out' }, 0.85)
 .to('#hero-logo-3d', { opacity: 1, x: 0, duration: 1.2, ease: 'bounce.out' }, 0.5)
 .to('#hero-stats', { opacity: 1, duration: 0.4 }, 1.0)
 .from('#hero-stats .hstat', { y: 40, opacity: 0, stagger: 0.12, duration: 0.7, ease: 'power3.out' }, 1.0)
 .to('#scroll-hint', { opacity: 1, duration: 0.6 }, 1.4);
 gsap.to('.orb-1', { y: -40, x: 30, duration: 6, ease: 'sine.inOut', yoyo: true, repeat: -1 });
 gsap.to('.orb-2', { y: 50, x: -20, duration: 8, ease: 'sine.inOut', yoyo: true, repeat: -1, delay: 1 });
 gsap.to('.orb-3', { y: -30, x: 40, duration: 5, ease: 'sine.inOut', yoyo: true, repeat: -1, delay: 2 });
 gsap.to('#hero-logo-3d', {
 rotateY: 8, rotateX: 4,
 duration: 4, ease: 'sine.inOut', yoyo: true, repeat: -1,
 transformOrigin: 'center center'
 });
 });
 gsap.set('#hero-desc, #hero-btns, #hero-stats, #scroll-hint', { opacity: 0 });
 gsap.set('.hero-tag', { opacity: 0, y: 20 });
 gsap.set('#hero-logo-3d', { opacity: 0, x: 60 });
 gsap.set('#hero-title .line1, #hero-title .line2', { y: 0 });
 // ──────────────── SCROLL-TRIGGERED REVEALS (páginas externas) ────────────────
 // Registrados desde pages.html tras el fetch, no aquí.
 gsap.to('#hero-title .line1', {
 scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.5 },
 x: -60, opacity: 0
 });
 gsap.to('#hero-title .line2', {
 scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1 },
 x: 60, opacity: 0
 });
 gsap.utils.toArray('.hstat-num').forEach(el => {
 ScrollTrigger.create({
 trigger: el,
 start: 'top 85%',
 once: true,
 onEnter: () => {
 gsap.from(el, { scale: 0.5, opacity: 0, duration: 0.8, ease: 'elastic.out(1, 0.7)' });
 }
 });
 });
 // ──────────────── PLAN CARD HOVER ────────────────
 document.querySelectorAll('.plan-card').forEach(card => {
 card.addEventListener('mousemove', e => {
 const rect = card.getBoundingClientRect();
 const nx = (e.clientX - rect.left) / rect.width - 0.5;
 const ny = (e.clientY - rect.top) / rect.height - 0.5;
 gsap.to(card, { rotateY: nx * 6, rotateX: -ny * 4, duration: 0.4, ease: 'power2.out', transformPerspective: 800 });
 });
 card.addEventListener('mouseleave', () => {
 gsap.to(card, { rotateY: 0, rotateX: 0, duration: 0.6, ease: 'elastic.out(1, 0.7)' });
 });
 });
 document.querySelectorAll('.btn-primary, .btn-orange').forEach(btn => {
 btn.addEventListener('mousemove', e => {
 const rect = btn.getBoundingClientRect();
 const nx = (e.clientX - rect.left - rect.width / 2) / rect.width;
 const ny = (e.clientY - rect.top - rect.height / 2) / rect.height;
 gsap.to(btn, { x: nx * 8, y: ny * 4, duration: 0.3, ease: 'power2.out' });
 });
 btn.addEventListener('mouseleave', () => {
 gsap.to(btn, { x: 0, y: 0, duration: 0.5, ease: 'elastic.out(1, 0.7)' });
 });
 });
 // ──────────────── FAQ TOGGLE ────────────────
 function toggleFaq(q) {
 const item = q.parentElement;
 const isOpen = item.classList.contains('open');
 document.querySelectorAll('.faq-item.open').forEach(i => i.classList.remove('open'));
 if (!isOpen) {
 item.classList.add('open');
 gsap.from(item.querySelector('.faq-a'), { y: -10, opacity: 0, duration: 0.4, ease: 'power2.out' });
 }
 }
 // ──────────────── PRICING LOGIC ────────────────
 function price(pk, days) {
 const p = PLANS[pk];
 if (pk === 'lifetime') return p.base;
 return p.base + Math.max(0, Math.floor((days - 30) / 30)) * p.xpm;
 }
 function upd(pk, days) {
 days = parseInt(days);
 PLANS[pk].days = days;
 const tot = price(pk, days);
 const extra = Math.max(0, Math.floor((days - 30) / 30));
 if (pk !== 'lifetime') {
 document.getElementById('dv-' + pk).textContent = days >= 365 ? '1 año (365d)' : days + ' días';
 document.getElementById('pn-' + pk).textContent = Math.floor(tot);
 document.getElementById('pd-' + pk).textContent = ((tot % 1) * 100).toFixed(0).padStart(2, '0');
 document.getElementById('px-' + pk).textContent = extra > 0 ? `+${extra} mes${extra > 1 ? 'es' : ''} extra` : '30 días incluidos';
 }
 document.getElementById('tot-' + pk).textContent = '€' + tot.toFixed(2);
 document.getElementById('sl-' + pk) && (document.getElementById('sl-' + pk).value = days);
 document.querySelectorAll(`.pc-${pk} .dpr`).forEach(b => {
 const map = { '30d': 30, '90d': 90, '6m': 180, '1 año': 365 };
 b.classList.toggle('on', map[b.textContent.trim()] === days);
 });
 }
 function sd(pk, d) { upd(pk, d); }
 // ──────────────── DESCUENTOS ────────────────
 function _recalcTotal() {
 if (!activePlan) return;
 const tot = price(activePlan, PLANS[activePlan].days);
 const discounted = activeDiscount.pct > 0
 ? Math.max(0, tot * (1 - activeDiscount.pct / 100))
 : tot;
 document.getElementById('o-total').textContent = '€' + discounted.toFixed(2);
 const row = document.getElementById('o-disc-row');
 if (activeDiscount.pct > 0) {
 row.style.display = 'flex';
 document.getElementById('o-disc-val').textContent =
 `-${activeDiscount.pct}% (−€${(tot - discounted).toFixed(2)})`;
 } else {
 row.style.display = 'none';
 }
 // Actualizar texto del separador según precio
 const sepTxt = document.getElementById('pp-sep-txt');
 if (sepTxt) sepTxt.textContent = discounted <= 0 ? 'Obtener clave' : 'Pagar con';
 buildPayPal(discounted, activePlan);
 }
 async function applyDiscount() {
 const code = (document.getElementById('f-disc-code').value || '').trim().toUpperCase();
 const msg = document.getElementById('disc-msg');
 if (!code) { msg.style.color = '#ff8fa3'; msg.textContent = '✘ Introduce un código.'; return; }
 msg.style.color = '#888'; msg.textContent = 'Validando...';
 try {
 const plan = activePlan || '';
 const r = await fetch(RENDER_URL + '/api/discount_codes/validate', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({ code, plan })
 });
 const d = await r.json();
 if (d.valid) {
 activeDiscount = { code, pct: d.discount };
 msg.style.color = '#2bc47a';
 msg.textContent = d.message;
 } else {
 activeDiscount = { code: '', pct: 0 };
 msg.style.color = '#ff8fa3';
 msg.textContent = d.message || '✘ Código no válido.';
 }
 _recalcTotal();
 } catch(e) {
 msg.style.color = '#ff8fa3'; msg.textContent = '✘ Error al conectar con el servidor.';
 }
 }
 // ──────────────── CHECKOUT ────────────────
 function openBuy(pk) {
 activePlan = pk;
 activeDiscount = { code: '', pct: 0 };
 const dcField = document.getElementById('f-disc-code');
 const dcMsg = document.getElementById('disc-msg');
 const dcRow = document.getElementById('o-disc-row');
 if (dcField) dcField.value = '';
 if (dcMsg) dcMsg.textContent = '';
 if (dcRow) dcRow.style.display = 'none';
 const p = PLANS[pk], tot = price(pk, p.days);
 const extra = pk === 'lifetime' ? 0 : Math.max(0, Math.floor((p.days - 30) / 30));
 const xCost = (tot - p.base).toFixed(2);
 document.getElementById('m-dot').style.cssText = `background:${p.col};box-shadow:0 0 14px ${p.col};`;
 document.getElementById('m-name').style.color = p.col;
 document.getElementById('m-name').textContent = p.name;
 document.getElementById('o-plan').textContent = p.name;
 
 document.getElementById('o-days').textContent = pk === 'lifetime' ? '∞ Lifetime' : p.days + ' días';
 document.getElementById('o-base').textContent = '€' + p.base.toFixed(2);
 document.getElementById('o-extra').textContent = extra > 0 ? `€${xCost} (+${extra}m)` : '€0.00';
 document.getElementById('o-total').textContent = '€' + tot.toFixed(2);
 document.getElementById('o-total').style.color = p.col;
 document.getElementById('s-form').style.display = 'block';
 document.getElementById('s-success').style.display = 'none';
 document.getElementById('al-checkout').classList.remove('show');
 document.getElementById('overlay').classList.add('open');
 gsap.from('.modal', { scale: 0.9, opacity: 0, duration: 0.5, ease: 'elastic.out(1, 0.7)' });
 // Show guard on open since fields are empty
 setTimeout(checkFields, 50);
 buildPayPal(tot, pk);
 }
 function closeBuy() {
 gsap.to('.modal', {
 scale: 0.92, opacity: 0, duration: 0.25, ease: 'power2.in',
 onComplete: () => {
 document.getElementById('overlay').classList.remove('open');
 gsap.set('.modal', { scale: 1, opacity: 1 });
 }
 });
 activePlan = null;
 }
 function showErr(msg) { const el = document.getElementById('al-checkout'); el.className = 'alert-b a-err show'; el.textContent = msg; }
 function hideErr() { document.getElementById('al-checkout').classList.remove('show'); }
 function checkFields() {
 const email = (document.getElementById('f-email').value || '').trim();
 const user = (document.getElementById('f-user').value || '').trim();
 const valid = email && /\S+@\S+\.\S+/.test(email) && user.length > 0;
 const guard = document.getElementById('fields-guard');
 const ppBtn = document.getElementById('pp-btn');
 const freeBtn = document.getElementById('free-key-btn');
 if (guard) guard.style.display = valid ? 'none' : 'block';
 if (ppBtn) ppBtn.style.opacity = valid ? '1' : '0.25';
 if (ppBtn) ppBtn.style.pointerEvents = valid ? 'auto' : 'none';
 if (freeBtn) freeBtn.disabled = !valid;
 // Highlight empty fields
 const emailInp = document.getElementById('f-email');
 const userInp = document.getElementById('f-user');
 if (emailInp) emailInp.style.borderColor = (email && /\S+@\S+\.\S+/.test(email)) ? '' : (email ? '#ff8fa3' : 'rgba(155,48,255,.5)');
 if (userInp) userInp.style.borderColor = user ? '' : 'rgba(155,48,255,.5)';
 }
 function buildPayPal(amount, pk) {
 const wrap = document.getElementById('pp-btn');
 wrap.innerHTML = '';
 // ── Código de descuento al 100%: mostrar botón de clave gratuita ──
 if (amount <= 0) {
 wrap.innerHTML = `
 <div style="margin-bottom:10px">
 <div style="font-family:var(--mono);font-size:10px;color:#2bc47a;text-align:center;
 padding:10px 16px;border:1px solid rgba(43,196,122,.3);border-radius:10px;
 background:rgba(43,196,122,.07);margin-bottom:14px;letter-spacing:1px">
 🎉 ¡Descuento del 100% aplicado! Tu licencia es completamente gratuita.
 </div>
 <button id="free-key-btn" onclick="claimFreeKey()"
 style="width:100%;padding:15px;background:linear-gradient(135deg,#2bc47a,#00e090);
 color:#000;border:none;border-radius:12px;font-family:var(--mono);
 font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
 cursor:pointer;box-shadow:0 8px 32px rgba(43,196,122,.35);
 transition:transform .2s,box-shadow .2s"
 onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 14px 40px rgba(43,196,122,.5)'"
 onmouseout="this.style.transform='';this.style.boxShadow='0 8px 32px rgba(43,196,122,.35)'">
 ✦ Obtener mi clave gratis
 </button>
 </div>`;
 return;
 }
 if (typeof paypal === 'undefined') {
 wrap.innerHTML = '<div style="font-family:var(--mono);font-size:12px;color:#ff8fa3;padding:18px;text-align:center;border:1px solid rgba(255,68,102,.3);border-radius:10px;">⚠ Configura tu PayPal Client ID en el script de la cabecera.</div>';
 return;
 }
 paypal.Buttons({
 style: { layout: 'vertical', color: 'blue', shape: 'rect', label: 'pay', height: 46 },
 createOrder: (data, actions) => {
 const email = document.getElementById('f-email').value.trim();
 const user = document.getElementById('f-user').value.trim();
 if (!email || !/\S+@\S+\.\S+/.test(email)) { showErr('✘ Introduce un email válido.'); return Promise.reject(); }
 if (!user) { showErr('✘ Introduce tu nombre de usuario.'); return Promise.reject(); }
 hideErr();
 return actions.order.create({ purchase_units: [{ description: `CastTweaks® ${PLANS[pk].name}`, amount: { value: amount.toFixed(2), currency_code: 'EUR' } }] });
 },
 onApprove: async (data, actions) => {
 try {
 const d = await actions.order.capture();
 await genLicense(pk, document.getElementById('f-user').value.trim(), document.getElementById('f-email').value.trim(), d.id, activeDiscount.code);
 } catch (e) { showErr('✘ Error al procesar: ' + (e.message || e)); }
 },
 onError: () => showErr('✘ Error de PayPal.'),
 onCancel: () => { const el = document.getElementById('al-checkout'); el.className = 'alert-b a-info show'; el.textContent = 'Pago cancelado.'; }
 }).render('#pp-btn');
 }
 async function claimFreeKey() {
 const email = document.getElementById('f-email').value.trim();
 const user = document.getElementById('f-user').value.trim();
 if (!email || !/\S+@\S+\.\S+/.test(email)) { showErr('✘ Introduce un email válido.'); return; }
 if (!user) { showErr('✘ Introduce tu nombre de usuario.'); return; }
 hideErr();
 const btn = document.getElementById('free-key-btn');
 if (btn) { btn.disabled = true; btn.innerHTML = '<span class="sp"></span> Generando clave...'; }
 const pk = activePlan;
 const p = PLANS[pk];
 const days = pk === 'lifetime' ? 36500 : p.days;
 const discountCode = activeDiscount.code;
 try {
 const { ts, sig } = await _hmacSign([user, email, discountCode]);
 const r = await fetch(RENDER_URL + '/api/issue_free', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 username: user,
 email: email,
 days: days,
 license_type: LICENSE_TYPE_MAP[pk] || p.type,
 max_devices: p.devs,
 plan: pk,
 discount_code: discountCode,
 ts,
 sig
 })
 });
 const data = await r.json();
 if (data.key) {
 document.getElementById('s-form').style.display = 'none';
 document.getElementById('s-success').style.display = 'block';
 document.getElementById('suc-key').textContent = data.key;
 document.getElementById('suc-meta').innerHTML =
 `Plan:
<b style="color:var(--white)">${p.name}</b> &nbsp;·&nbsp; Duración: <b style="color:var(--white)">${days >= 36500 ? '∞ Lifetime' : days + ' días'}</b><br>Expira: <b style="color:var(--white)">${data.expires || '—'}</b>`;
 gsap.from('.suc-icon', { scale: 0, rotation: -90, duration: 0.7, ease: 'elastic.out(1, 0.7)' });
 } else {
 showErr('✘ ' + (data.error || 'No se pudo emitir la clave.'));
 if (btn) { btn.disabled = false; btn.innerHTML = '✦ Obtener mi clave gratis'; }
 }
 } catch (e) {
 showErr('✘ Error de red. Inténtalo de nuevo.');
 if (btn) { btn.disabled = false; btn.innerHTML = '✦ Obtener mi clave gratis'; }
 }
 }

 const p = PLANS[pk];
 const days = pk === 'lifetime' ? 36500 : p.days;
 try {
 const { ts, sig } = await _hmacSign([username, email, orderId]);
 const r = await fetch(RENDER_URL + '/api/issue_public', {
 method: 'POST',
 headers: { 'Content-Type': 'application/json' },
 body: JSON.stringify({
 username,
 email,
 days,
 license_type: LICENSE_TYPE_MAP[pk] || p.type,
 max_devices: p.devs,
 paypal_order_id: orderId,
 plan: pk,
 discount_code: discountCode,
 ts,
 sig
 })
 });
 const data = await r.json();
 if (data.key) {
 document.getElementById('s-form').style.display = 'none';
 document.getElementById('s-success').style.display = 'block';
 document.getElementById('suc-key').textContent = data.key;
 document.getElementById('suc-meta').innerHTML =
 `Plan:
<b style="color:var(--white)">${p.name}</b> &nbsp;·&nbsp; Duración: <b style="color:var(--white)">${days >= 36500 ? '∞ Lifetime' : days + ' días'}</b><br>Expira: <b style="color:var(--white)">${data.expires || '—'}</b>`;
 gsap.from('.suc-icon', { scale: 0, rotation: -90, duration: 0.7, ease: 'elastic.out(1, 0.7)' });
 } else {
 showErr('✘ ' + (data.error || 'Error. Guarda tu ID: ' + orderId));
 }
 } catch (e) {
 showErr('✘ Error de red. ID de pago: ' + orderId);
 }
 }
 function copyKey() {
 navigator.clipboard.writeText(document.getElementById('suc-key').textContent).then(() => {
 const b = document.getElementById('copy-btn');
 b.textContent = '✓ Copiada';
 gsap.from(b, { scale: 1.2, duration: 0.3, ease: 'power2.out' });
 setTimeout(() => b.textContent = 'Copiar', 1600);
 });
 }
 document.getElementById('yr').textContent = new Date().getFullYear();
 /* ─── FLOATING NAV: show after scroll + active section highlight ─── */
 (function () {
 const floatNav = document.getElementById('float-nav');
 if (!floatNav) return;
 const fnItems = floatNav.querySelectorAll('[data-section]');
 const pageSections = [
 { id: 'hero', el: document.querySelector('.hero') },
 { id: 'features', el: document.getElementById('features') },
 { id: 'pricing', el: document.getElementById('pricing') },
 { id: 'faq', el: document.getElementById('faq') },
 { id: 'resenas', el: document.getElementById('reviews-testimonials') }
 ];

 /* ── Visibility on scroll ── */
 function onScroll() {
 if (window.scrollY > 140) floatNav.classList.add('fn-visible');
 else floatNav.classList.remove('fn-visible');
 updateActive();
 }

 /* ── Active section highlight ── */
 function updateActive() {
 const mid = window.scrollY + window.innerHeight * 0.45;
 let current = pageSections[0].id;
 for (const s of pageSections) {
 if (!s.el) continue;
 if (s.el.offsetTop <= mid) current = s.id;
 }
 fnItems.forEach(function(a) {
 a.classList.toggle('fn-active', a.dataset.section === current && !a.classList.contains('fn-cta'));
 });
 }

 window.addEventListener('scroll', onScroll, { passive: true });
 onScroll();

 /* ════════════════════════════════════════
 GSAP MAGNETIC EFFECT
 ════════════════════════════════════════ */
 if (typeof gsap === 'undefined') return;

 const MAG = 0.38;
 const RAD = 90;
 const EASE_OUT = 'power2.out';
 const EASE_ELASTIC = 'elastic.out(1, 0.55)';
 const DUR_RETURN = 0.5;

 /* ── Breathing glow on the whole nav bar ── */
 gsap.to(floatNav, {
 boxShadow: '0 8px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04) inset, 0 0 44px rgba(155,48,255,0.3)',
 duration: 2,
 repeat: -1,
 yoyo: true,
 ease: 'sine.inOut',
 });

 floatNav.querySelectorAll('.fn-item').forEach(function(btn) {
 var icon = btn.querySelector('svg');
 var label = btn.querySelector('.fn-label');

 /* ── Mouse enter: pre-scale icon ── */
 btn.addEventListener('mouseenter', function() {
 if (icon) gsap.to(icon, { scale: 1.38, duration: 0.22, ease: EASE_OUT, overwrite: true });
 gsap.to(btn, { '--glow-opacity': 1, duration: 0.2 });
 });

 /* ── Mouse move: magnetic pull ── */
 btn.addEventListener('mousemove', function(e) {
 var rect = btn.getBoundingClientRect();
 var cx = rect.left + rect.width / 2;
 var cy = rect.top + rect.height / 2;
 var dx = e.clientX - cx;
 var dy = e.clientY - cy;
 var dist = Math.sqrt(dx * dx + dy * dy);
 var f = Math.max(0, 1 - dist / RAD) * MAG;

 /* Button body follows cursor */
 gsap.to(btn, {
 x: dx * f * 1.6,
 y: dy * f * 1.2,
 duration: 0.18,
 ease: EASE_OUT,
 overwrite: true,
 });

 /* Icon follows more aggressively for depth */
 if (icon) {
 gsap.to(icon, {
 x: dx * f * 0.8,
 y: dy * f * 0.65,
 scale: 1.38,
 duration: 0.14,
 ease: EASE_OUT,
 overwrite: true,
 });
 }

 /* Label slides gently */
 if (label) {
 gsap.to(label, {
 x: dx * f * 0.25,
 duration: 0.2,
 ease: EASE_OUT,
 overwrite: true,
 });
 }
 });

 /* ── Mouse leave: elastic snap back ── */
 btn.addEventListener('mouseleave', function() {
 gsap.to(btn, { x: 0, y: 0, duration: DUR_RETURN, ease: EASE_ELASTIC, overwrite: true });
 if (icon) gsap.to(icon, { x: 0, y: 0, scale: 1, duration: DUR_RETURN, ease: EASE_ELASTIC, overwrite: true });
 if (label) gsap.to(label, { x: 0, duration: DUR_RETURN * 0.7, ease: EASE_ELASTIC, overwrite: true });
 });

 /* ── Click: squish + flash ── */
 btn.addEventListener('click', function() {
 gsap.timeline()
 .to(btn, { scale: 0.86, duration: 0.08, ease: 'power3.in' })
 .to(btn, { scale: 1, duration: 0.6, ease: 'elastic.out(1.3, 0.5)' });
 if (icon) {
 gsap.fromTo(icon,
 { filter: 'drop-shadow(0 0 0px rgba(224,64,251,0))' },
 { filter: 'drop-shadow(0 0 16px rgba(224,64,251,1)) drop-shadow(0 0 32px rgba(155,48,255,0.9))',
 duration: 0.15, yoyo: true, repeat: 1 }
 );
 }
 });
 });
})();
 document.getElementById('overlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeBuy(); });
 document.addEventListener('keydown', e => { if (e.key === 'Escape') closeBuy(); });
 document.querySelectorAll('.feat-icon-wrap').forEach(icon => {
 icon.parentElement.addEventListener('mouseenter', () => {
 gsap.to(icon, { rotation: 15, scale: 1.15, duration: 0.35, ease: 'power2.out' });
 });
 icon.parentElement.addEventListener('mouseleave', () => {
 gsap.to(icon, { rotation: 0, scale: 1, duration: 0.5, ease: 'elastic.out(1, 0.7)' });
 });
 });

/* ══════════════════════════════════════════ */

/* ── Hamburger menu ── */
 function closeMobileMenu() {
 const btn = document.getElementById('nav-hamburger');
 const menu = document.getElementById('nav-mobile-menu');
 if (btn && menu) {
 btn.classList.remove('open');
 btn.setAttribute('aria-expanded', 'false');
 menu.classList.remove('open');
 menu.setAttribute('aria-hidden', 'true');
 }
 }
 const hamburgerBtn = document.getElementById('nav-hamburger');
 const mobileMenu = document.getElementById('nav-mobile-menu');
 if (hamburgerBtn && mobileMenu) {
 hamburgerBtn.addEventListener('click', function() {
 const isOpen = this.classList.toggle('open');
 mobileMenu.classList.toggle('open');
 this.setAttribute('aria-expanded', isOpen);
 mobileMenu.setAttribute('aria-hidden', !isOpen);
 });
 // Close on outside click
 document.addEventListener('click', function(e) {
 if (!hamburgerBtn.contains(e.target) && !mobileMenu.contains(e.target)) {
 closeMobileMenu();
 }
 });
 // Close on scroll
 window.addEventListener('scroll', function() {
 closeMobileMenu();
 }, { passive: true });
 }

/* ═══════════════════════════════════════════════════════════════════
   ✦ 3D TILT — PLAN CARDS (standalone, sin dependencia de ScrollTrigger)
═══════════════════════════════════════════════════════════════════ */
(function () {
  function initTilt() {
    const cards = document.querySelectorAll('.plan-card');
    if (!cards.length || typeof gsap === 'undefined') return;

    const MAX_TILT = 15;

    cards.forEach(function (card) {
      /* Estado inicial limpio */
      gsap.set(card, { rotateX: 0, rotateY: 0, scale: 1, z: 0, transformPerspective: 1000 });

      /* --- Entrada stagger --- */
      var idx = Array.from(card.parentElement.children).indexOf(card);
      gsap.from(card, {
        opacity: 0,
        rotateX: 18,
        y: 40,
        scale: 0.94,
        duration: 0.85,
        delay: idx * 0.14 + 0.1,
        ease: 'power3.out',
        clearProps: 'opacity',
      });

      /* --- Mousemove tilt --- */
      card.addEventListener('mousemove', function (e) {
        var rect = card.getBoundingClientRect();
        var dx   = (e.clientX - rect.left - rect.width  / 2) / (rect.width  / 2);
        var dy   = (e.clientY - rect.top  - rect.height / 2) / (rect.height / 2);

        /* Spotlight CSS */
        var px = ((e.clientX - rect.left) / rect.width)  * 100;
        var py = ((e.clientY - rect.top)  / rect.height) * 100;
        card.style.setProperty('--mx', px + '%');
        card.style.setProperty('--my', py + '%');

        gsap.to(card, {
          rotateY:  dx * MAX_TILT,
          rotateX: -dy * MAX_TILT,
          scale: 1.04,
          z: 30,
          duration: 0.3,
          ease: 'power2.out',
          overwrite: 'auto',
          transformPerspective: 1000,
        });
      });

      /* --- Mouse leave: snap back --- */
      card.addEventListener('mouseleave', function () {
        card.style.removeProperty('--mx');
        card.style.removeProperty('--my');
        gsap.to(card, {
          rotateX: 0,
          rotateY: 0,
          scale: 1,
          z: 0,
          duration: 0.65,
          ease: 'elastic.out(1, 0.55)',
          overwrite: 'auto',
        });
      });

      /* --- Click squish --- */
      card.addEventListener('mousedown', function () {
        gsap.to(card, { scale: 0.96, z: -8, duration: 0.12, ease: 'power3.in', overwrite: 'auto' });
      });
      card.addEventListener('mouseup', function () {
        gsap.to(card, { scale: 1.04, z: 30, duration: 0.5, ease: 'elastic.out(1, 0.7)', overwrite: 'auto' });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTilt);
  } else {
    initTilt();
  }
})();

/* ═══════════════════════════════════════════════════════════════════
   ✦ GSAP ANIMATION TRIGGERS — CastTweaks® Enhanced
   Activa clases CSS de animación + efectos adicionales con GSAP
═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── 1. IntersectionObserver: activa .is-visible en .gsap-fade-up y .hstat ── */
  const revealObs = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          revealObs.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
  );

  document.querySelectorAll('.gsap-fade-up, .hstat').forEach((el) => {
    revealObs.observe(el);
  });

  /* ── 2. Cursor mejorado: añade cursor-hover y cursor-click ── */
  const ring = document.getElementById('cursor-ring');
  if (ring) {
    const hoverables = 'a, button, .btn, .fn-item, .dpr, .faq-q, .plan-card, .feat-item, .testi-header, .copy-b, .modal-x';
    document.querySelectorAll(hoverables).forEach((el) => {
      el.addEventListener('mouseenter', () => ring.classList.add('cursor-hover'));
      el.addEventListener('mouseleave', () => ring.classList.remove('cursor-hover'));
    });
    document.addEventListener('mousedown', () => ring.classList.add('cursor-click'));
    document.addEventListener('mouseup', () => ring.classList.remove('cursor-click'));
  }

  /* ── 3. GSAP ScrollTrigger: animar rating bars al entrar en vista ── */
  if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);

    /* Rating bars: animar width desde 0 */
    gsap.utils.toArray('.rs-bar-fill').forEach((bar) => {
      const targetW = bar.style.width || bar.getAttribute('data-width') || '80%';
      bar.style.width = '0%';
      gsap.to(bar, {
        width: targetW,
        duration: 1.4,
        ease: 'power3.out',
        scrollTrigger: {
          trigger: bar,
          start: 'top 85%',
          once: true,
        },
      });
    });

    /* Feature grid: stagger desde scroll */
    gsap.utils.toArray('.feat-item').forEach((item, i) => {
      gsap.fromTo(
        item,
        { opacity: 0, y: 36, scale: 0.97 },
        {
          opacity: 1, y: 0, scale: 1,
          duration: 0.7,
          delay: i * 0.08,
          ease: 'power3.out',
          scrollTrigger: {
            trigger: item,
            start: 'top 88%',
            once: true,
          },
        }
      );
    });

    /* Opt-pills stagger */
    gsap.utils.toArray('.opt-pill').forEach((pill, i) => {
      gsap.fromTo(
        pill,
        { opacity: 0, x: -20 },
        {
          opacity: 1, x: 0,
          duration: 0.6,
          delay: i * 0.12,
          ease: 'power2.out',
          scrollTrigger: {
            trigger: pill,
            start: 'top 90%',
            once: true,
          },
        }
      );
    });

    /* FAQ items: entrada alterna izquierda/derecha */
    gsap.utils.toArray('.faq-item').forEach((item, i) => {
      gsap.fromTo(
        item,
        { opacity: 0, x: i % 2 === 0 ? -24 : 24 },
        {
          opacity: 1, x: 0,
          duration: 0.55,
          ease: 'power2.out',
          scrollTrigger: {
            trigger: item,
            start: 'top 88%',
            once: true,
          },
        }
      );
    });

    /* Hero orbs: GSAP parallax en scroll */
    gsap.to('.orb-1', {
      y: -80,
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.5 },
    });
    gsap.to('.orb-2', {
      y: 60,
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 2 },
    });
    gsap.to('.orb-3', {
      y: -40, x: 30,
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1 },
    });

    /* Section titles: clip-path reveal */
    gsap.utils.toArray('.section-title').forEach((title) => {
      gsap.fromTo(
        title,
        { clipPath: 'inset(0 100% 0 0)', opacity: 0 },
        {
          clipPath: 'inset(0 0% 0 0)',
          opacity: 1,
          duration: 0.9,
          ease: 'power3.out',
          scrollTrigger: {
            trigger: title,
            start: 'top 85%',
            once: true,
          },
        }
      );
    });

    /* Testimonial items: entrada escalonada */
    gsap.utils.toArray('.testi-item').forEach((item, i) => {
      gsap.fromTo(
        item,
        { opacity: 0, y: 30, scale: 0.97 },
        {
          opacity: 1, y: 0, scale: 1,
          duration: 0.65,
          delay: i * 0.1,
          ease: 'power2.out',
          scrollTrigger: {
            trigger: item,
            start: 'top 88%',
            once: true,
          },
        }
      );
    });

    /* Hero stats: counter number animation */
    gsap.utils.toArray('.hstat-num').forEach((el) => {
      const raw = el.textContent.trim();
      const num = parseFloat(raw.replace(/[^\d.]/g, ''));
      const suffix = raw.replace(/[\d.]/g, '');
      if (!isNaN(num)) {
        gsap.fromTo(
          { val: 0 },
          { val: num,
            duration: 1.8,
            ease: 'power2.out',
            onUpdate: function () {
              const v = this.targets()[0].val;
              el.textContent = (Number.isInteger(num) ? Math.round(v) : v.toFixed(1)) + suffix;
            },
            scrollTrigger: { trigger: el, start: 'top 85%', once: true },
          }
        );
      }
    });

    /* ── 4. Breathing glow en pc-pro ── */
    gsap.to('.pc-pro', {
      boxShadow: '0 0 80px rgba(224,64,251,0.22)',
      duration: 2,
      repeat: -1,
      yoyo: true,
      ease: 'sine.inOut',
    });

    /* ── 5. Marquee pause on hover: CSS animation-play-state (no GSAP) ── */
    document.querySelectorAll('.rmarquee-lane').forEach((lane) => {
      lane.addEventListener('mouseenter', () => {
        lane.style.animationPlayState = 'paused';
      });
      lane.addEventListener('mouseleave', () => {
        lane.style.animationPlayState = 'running';
      });
    });
  }

})();
