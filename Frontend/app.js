// ============================================================
// Sankhya Setu — shared app.js, loaded on every page.
//
// This file used to be one inline <script> inside a single-page app,
// where every screen's HTML coexisted in the DOM and "navigation" just
// toggled which <section> had the .active class. Now each screen is its
// own real HTML file, so:
//   - goScreen(name) does a real page navigation (location.href), not a
//     class toggle.
//   - Every block that touches an element belonging to only ONE screen
//     (e.g. #spinMark, #role-list, #dropzone, #course-chips) is guarded
//     with an existence check, since this same app.js loads on pages
//     that don't have that element at all.
//   - Data that used to flow between screens via shared in-memory
//     variables (quiz source, review data, "which screen did I come
//     from") now flows via URL query params, since a real page load
//     resets plain JS variables. The signup wizard is the one exception
//     — it's kept as a single page (signup.html) with its original
//     internal step-toggling, because carrying password fields across
//     real page loads via the URL would be unsafe.
// ============================================================

// ---------- Supabase client (declared first, before anything else can throw) ----------
const SUPABASE_URL = 'https://hvkkwapsnmaalcqzmyfh.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_28mh4OF6mfGsqN2eyrtH7w_EgliBmqw';
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);

// The Python/LangChain quiz-generation backend (main.py). Currently
// only running locally — update this once it's actually deployed.
const BACKEND_URL = 'https://backend-d6en760jk-teamterminal.vercel.app';

// ---------- cross-page navigation ----------
// The signup wizard's 6 steps live in ONE file (signup.html), so any
// goScreen('signup-…') call — e.g. the "Create an account" link on the
// login page — should land on that single file, not a nonexistent
// "signup-1.html".
function goScreen(name) {
  const fileMap = { landing: 'index' };
  const target = name.startsWith('signup') ? 'signup' : (fileMap[name] || name);
  window.location.href = target + '.html';
}

function initials(name) {
  if (!name) return '--';
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '--';
}

function toggleDemoMenu() {
  document.getElementById('demoMenu').classList.toggle('show');
}
function jump(name) {
  goScreen(name);
}

// ---- dashboard sidebar + tabs (dashboard.html only) ----
function toggleSidebar() {
  const sb = document.getElementById('appSidebar');
  const bd = document.getElementById('sidebarBackdrop');
  if (sb) sb.classList.toggle('open');
  if (bd) bd.classList.toggle('show');
}
function switchDashTab(tab) {
  ['overview', 'results', 'progress'].forEach(t => {
    const btn = document.getElementById('tab-' + t);
    const panel = document.getElementById('panel-' + t);
    if (btn) btn.classList.toggle('active', t === tab);
    if (panel) panel.style.display = (t === tab) ? 'block' : 'none';
  });
}

// ============================================================
// Session-aware bits: fab visibility + profile hydration.
// Runs on every page via initPage() at the bottom of this file.
// ============================================================
const APP_SCREENS = ['dashboard', 'role', 'upload', 'spin', 'quiz', 'results', 'practice', 'progress'];
let currentUser = null;
let quizTaken = false;
let readinessScore = 0;

async function initPage() {
  const screen = document.body.dataset.screen;
  const fab = document.getElementById('profileFab');

  const sidebarPageMap = {
    dashboard: 'dashboard.html', role: 'role.html', upload: 'upload.html',
    progress: 'progress.html', practice: 'practice.html', profile: 'profile.html',
    'igot-courses': 'igot-courses.html'
  };
  const activeHref = sidebarPageMap[screen];
  document.querySelectorAll('.sb-link').forEach(link => {
    if (link.tagName === 'A') link.classList.toggle('active', link.getAttribute('href') === activeHref);
  });

  const { data: { session } } = await supabaseClient.auth.getSession();

  if (session) {
    const { data: profile } = await supabaseClient
      .from('profiles')
      .select('*, ministries(name), job_roles(name)')
      .eq('id', session.user.id)
      .single();

    currentUser = {
      id: session.user.id,
      name: profile?.full_name || '',
      email: session.user.email || '',
      ministry: profile?.ministries?.name || '',
      designation: profile?.job_roles?.name || '',
      years: profile?.years_in_role,
      qualification: profile?.qualification || '',
      field: profile?.field_of_study || '',
      photo: null
    };

    if (fab) {
      const showFab = screen !== 'profile' && APP_SCREENS.includes(screen);
      fab.style.display = showFab ? 'flex' : 'none';
      const fabInitials = document.getElementById('fabInitials');
      if (fabInitials) fabInitials.textContent = initials(currentUser.name);
      fab.setAttribute('onclick', "location.href='profile.html?from=" + screen + "'");
    }

    const sbName = document.getElementById('sbUserName');
    const sbRole = document.getElementById('sbUserRole');
    if (sbName) sbName.textContent = currentUser.name || 'Your profile';
    if (sbRole) sbRole.textContent = [currentUser.designation, currentUser.ministry].filter(Boolean).join(' · ') || 'Statistical Service';
  } else if (fab) {
    fab.style.display = 'none';
  }

  // ---- per-screen setup that used to happen inside goScreen() ----
  if (screen === 'profile') renderProfile();

  if (screen === 'dashboard') {
    if (currentUser) {
      const firstName = currentUser.name.split(' ')[0] || 'there';
      const gName = document.getElementById('dashGreetName');
      const gRole = document.getElementById('dashGreetRole');
      if (gName) gName.textContent = 'Welcome back, ' + firstName;
      if (gRole) gRole.textContent = [currentUser.designation, currentUser.ministry].filter(Boolean).join(' · ') || "Here's your learning snapshot.";
    }

    loadDashboardOverviewTab();
    loadDashboardResultsTab();
  }

  if (screen === 'results') {
    renderResults();
  }

  if (screen === 'practice') {
    loadRecommendedCourses();
  }

  if (screen === 'igot-courses') {
    loadIgotCourses();
  }

  if (screen === 'spin') {
    const params = new URLSearchParams(location.search);
    const step = params.get('step') || 'building';
    const source = params.get('source') || 'role';

    if (step === 'scoring') {
      document.getElementById('spin-title').textContent = 'Scoring your answers…';
      document.getElementById('spin-sub').textContent = 'Matching results against what your role requires.';
      runSubmitQuiz();
    } else {
      if (source !== 'role') {
        // Only the standard role-based quiz is wired up right now —
        // upload/reassess navigate here but there's no backend support
        // for them yet, so fail clearly rather than pretend to work.
        showSpinError("This quiz type isn't available yet — only the standard quiz works right now.");
        return;
      }
      document.getElementById('spin-title').textContent = 'Building your quiz…';
      document.getElementById('spin-sub').textContent = '20 quick questions across your role\'s key skills, generated just for you.';
      runGenerateQuiz();
    }
  }

  if (screen === 'quiz') {
    loadQuizData();
  }

  if (screen === 'signup-success-redirect-name') {
    // placeholder, unused — see signup.html's own inline handling instead
  }
}

// ---- profile screen ----
function triggerPhotoUpload() {
  document.getElementById('photoInput').click();
}

function handlePhotoUpload(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    currentUser.photo = e.target.result;
    renderProfile();
  };
  reader.readAsDataURL(file);
}

function renderProfile() {
  if (!currentUser) return;
  document.getElementById('profileName').textContent = currentUser.name || 'Your name';
  document.getElementById('profileRole').textContent =
    [currentUser.designation, currentUser.ministry].filter(Boolean).join(' · ') || 'Add your job details';
  document.getElementById('pf-email').textContent = currentUser.email || '—';
  document.getElementById('pf-ministry').textContent = currentUser.ministry || '—';
  document.getElementById('pf-desig').textContent = currentUser.designation || '—';
  document.getElementById('pf-years').textContent = (currentUser.years || currentUser.years === 0) ? currentUser.years : '—';
  document.getElementById('pf-qual').textContent = currentUser.qualification || '—';
  document.getElementById('pf-field').textContent = currentUser.field || '—';

  const ini = initials(currentUser.name);
  document.getElementById('avatarLgInitials').textContent = ini;
  document.getElementById('fabInitials').textContent = ini;

  const lgImg = document.getElementById('avatarLgImg');
  const lgInitials = document.getElementById('avatarLgInitials');
  const fabImg = document.getElementById('fabImg');
  const fabInitials = document.getElementById('fabInitials');
  const photoBtnLabel = document.getElementById('photoBtnLabel');

  if (currentUser.photo) {
    lgImg.src = currentUser.photo; lgImg.style.display = 'block'; lgInitials.style.display = 'none';
    fabImg.src = currentUser.photo; fabImg.style.display = 'block'; fabInitials.style.display = 'none';
    photoBtnLabel.textContent = 'Change profile photo';
  } else {
    lgImg.style.display = 'none'; lgInitials.style.display = 'block';
    fabImg.style.display = 'none'; fabInitials.style.display = 'block';
    photoBtnLabel.textContent = 'Upload profile photo';
  }

  document.getElementById('profile-progress-empty').style.display = quizTaken ? 'none' : 'block';
  document.getElementById('profile-progress-full').style.display = quizTaken ? 'block' : 'none';
  if (quizTaken) document.getElementById('pf-meter-num').textContent = readinessScore + '%';
}

async function signOut() {
  await supabaseClient.auth.signOut();
  currentUser = null;
  quizTaken = false;
  goScreen('landing');
}

// ---- landing page: animate the hero result meter once, on load ----
(function () {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const num = document.getElementById('heroMeterNum');
  if (!num) return;
  const segs = document.querySelectorAll('#heroMock .meter-seg i');
  if (reduce) {
    segs.forEach(s => s.style.width = (s.dataset.w || 0) + '%');
    num.textContent = '52%';
    return;
  }
  setTimeout(() => {
    segs.forEach(s => s.style.width = (s.dataset.w || 0) + '%');
    let n = 0; const target = 52;
    const t = setInterval(() => {
      n += 2;
      if (n >= target) { n = target; clearInterval(t); }
      num.textContent = n + '%';
    }, 22);
  }, 300);
})();

// ---- landing page: animate the "your gaps" ledger values when scrolled into view ----
(function () {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const box = document.getElementById('gapsMock');
  if (!box) return;
  const vals = box.querySelectorAll('.lval');
  if (reduce) {
    vals.forEach(v => v.textContent = v.dataset.target + '%');
    return;
  }
  let done = false;
  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting && !done) {
        done = true;
        vals.forEach((v, i) => {
          setTimeout(() => {
            const target = Number(v.dataset.target);
            let n = 0;
            const t = setInterval(() => {
              n += 2;
              if (n >= target) { n = target; clearInterval(t); }
              v.textContent = n + '%';
            }, 18);
          }, i * 90);
        });
        io.disconnect();
      }
    });
  }, { threshold: .4 });
  io.observe(box);
})();

// ---- spinner tally animation (spin.html only) ----
const spinMark = document.getElementById('spinMark');
if (spinMark) {
  for (let i = 0; i < 8; i++) {
    const b = document.createElement('div');
    b.className = 'bar';
    b.style.transform = `rotate(${i * 45}deg)`;
    b.style.animation = `tickfade 1s ${i * 0.1}s infinite`;
    spinMark.appendChild(b);
  }
}

// ---- login ----
function showPhone() {
  document.getElementById('mode-choice').style.display = 'none';
  document.getElementById('mode-phone').style.display = 'block';
  document.getElementById('mode-email').style.display = 'none';
  document.getElementById('back-to-choice').style.display = 'block';
}
function showEmailLogin() {
  document.getElementById('mode-choice').style.display = 'none';
  document.getElementById('mode-phone').style.display = 'none';
  document.getElementById('mode-email').style.display = 'block';
  document.getElementById('back-to-choice').style.display = 'block';
}
function showChoice() {
  document.getElementById('mode-choice').style.display = 'flex';
  document.getElementById('mode-phone').style.display = 'none';
  document.getElementById('mode-email').style.display = 'none';
  document.getElementById('back-to-choice').style.display = 'none';
}
async function loginWithEmail() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('login-submit-btn');
  errEl.classList.remove('show');

  if (!email || !password) {
    errEl.textContent = 'Enter both your email and password.';
    errEl.classList.add('show');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Signing in…';

  const { error } = await supabaseClient.auth.signInWithPassword({ email, password });

  btn.disabled = false;
  btn.textContent = 'Sign in';

  if (error) {
    console.error('Login failed:', error);
    errEl.textContent = error.message || 'Could not sign in. Check your email and password.';
    errEl.classList.add('show');
    return;
  }

  goScreen('dashboard');
}
function startGoogleLogin(btn) {
  // Demo stub — not wired to a real provider. Real accounts should use
  // "Continue with Email" above.
  const original = btn.innerHTML;
  btn.innerHTML = 'Signing in…';
  setTimeout(() => {
    alert('Google sign-in is a demo placeholder in this build. Use "Continue with Email" to sign in with a real account.');
    btn.innerHTML = original;
  }, 600);
}
function sendOtp() {
  const phone = document.getElementById('phone').value;
  if (phone.length !== 10) { alert('Enter a valid 10-digit mobile number.'); return; }
  document.getElementById('otp-block').style.display = 'block';
  document.getElementById('otp1').focus();
}
function otpNext(el) {
  if (el.value.length === 1 && el.nextElementSibling && el.nextElementSibling.classList.contains('otp')) {
    el.nextElementSibling.focus();
  }
}
function verifyOtp() {
  const vals = ['otp1', 'otp2', 'otp3', 'otp4'].map(id => document.getElementById(id).value);
  if (vals.some(v => v === '')) { alert('Enter all 4 digits.'); return; }
  alert('Mobile OTP sign-in is a demo placeholder in this build. Use "Continue with Email" to sign in with a real account.');
}

// ---- upload (upload.html only) ----
let selectedFile = null;

const dz = document.getElementById('dropzone');
if (dz) {
  ['dragenter', 'dragover'].forEach(evt => dz.addEventListener(evt, e => { e.preventDefault(); dz.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach(evt => dz.addEventListener(evt, e => { e.preventDefault(); dz.classList.remove('drag'); }));
  dz.addEventListener('drop', e => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleSelectedFile(file);
  });
}

function filePicked(input) {
  if (input.files.length) handleSelectedFile(input.files[0]);
}

function handleSelectedFile(file) {
  const errEl = document.getElementById('upload-file-error');
  if (file.type !== 'application/pdf') {
    errEl.textContent = 'Only PDF files are supported right now — please choose a .pdf file.';
    errEl.classList.add('show');
    document.getElementById('upload-continue').disabled = true;
    return;
  }
  errEl.classList.remove('show');
  selectedFile = file;
  showFilePicked(file.name);
}

function showFilePicked(name) {
  document.getElementById('fileName').textContent = name;
  document.getElementById('filePicked').classList.add('show');
  document.getElementById('upload-continue').disabled = false;
}

function resetUploadScreen() {
  selectedFile = null;
  document.getElementById('filePicked').classList.remove('show');
  document.getElementById('upload-continue').disabled = true;
  document.getElementById('fileInput').value = '';
  document.getElementById('upload-error').style.display = 'none';
  document.getElementById('upload-loading').style.display = 'none';
  document.getElementById('upload-picker').style.display = 'block';
}

async function uploadAndGenerateQuiz() {
  if (!selectedFile) return;
  if (!currentUser || !currentUser.id) {
    alert('You need to be signed in to take a quiz.');
    return;
  }

  document.getElementById('upload-picker').style.display = 'none';
  document.getElementById('upload-error').style.display = 'none';
  document.getElementById('upload-loading').style.display = 'block';

  const formData = new FormData();
  formData.append('profile_id', currentUser.id);
  formData.append('file', selectedFile);

  try {
    const res = await fetch(BACKEND_URL + '/generate-quiz-from-material', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'The quiz could not be generated from this material.');
    }
    if (data.skills_covered.length === 0) {
      throw new Error("This material didn't cover any of your role's required skills well enough to build a quiz from.");
    }

    // Same sessionStorage key and shape quiz.html already reads for
    // the standard quiz — no changes needed to quiz.html itself.
    sessionStorage.setItem('quizData', JSON.stringify({
      attempt_id: data.attempt_id,
      questions: data.questions
    }));

    if (data.skills_skipped.length > 0) {
      console.info('Skills skipped (not covered by this material):', data.skills_skipped);
    }

    window.location.href = 'quiz.html';
  } catch (err) {
    console.error('generate-quiz-from-material failed:', err);
    document.getElementById('upload-loading').style.display = 'none';
    document.getElementById('upload-error').style.display = 'block';
    document.getElementById('upload-error-message').textContent =
      err.message || 'Could not reach the quiz backend. Is it running?';
  }
}

// ---- quiz flow entry point (called from role.html and progress.html) ----
// upload.html handles its own file upload directly (see
// uploadAndGenerateQuiz above) rather than going through here, since a
// File object can't be handed off via sessionStorage the way
// everything else on this site passes data between pages.
function startQuiz(source) {
  if (source !== 'role') {
    alert("This quiz type isn't available yet — only the standard quiz works right now.");
    return;
  }
  window.location.href = 'spin.html?source=' + encodeURIComponent(source);
}

function showSpinError(message) {
  document.getElementById('spin-loading').style.display = 'none';
  const errBox = document.getElementById('spin-error');
  document.getElementById('spin-error-message').textContent = message;
  errBox.style.display = 'block';
}

async function runGenerateQuiz() {
  if (!currentUser || !currentUser.id) {
    showSpinError('You need to be signed in to take a quiz.');
    return;
  }
  try {
    const res = await fetch(BACKEND_URL + '/generate-quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: currentUser.id })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'The quiz could not be generated.');
    }
    sessionStorage.setItem('quizData', JSON.stringify(data));
    window.location.href = 'quiz.html';
  } catch (err) {
    console.error('generate-quiz failed:', err);
    showSpinError(err.message || 'Could not reach the quiz backend. Is it running?');
  }
}

async function runSubmitQuiz() {
  const raw = sessionStorage.getItem('quizSubmission');
  if (!raw) {
    showSpinError('Your quiz answers were lost. Please retake the quiz.');
    return;
  }
  const submission = JSON.parse(raw);
  try {
    const res = await fetch(BACKEND_URL + '/submit-quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(submission)
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'The quiz could not be scored.');
    }
    sessionStorage.setItem('quizResults', JSON.stringify(data));
    sessionStorage.removeItem('quizData');
    sessionStorage.removeItem('quizSubmission');
    window.location.href = 'results.html';
  } catch (err) {
    console.error('submit-quiz failed:', err);
    showSpinError(err.message || 'Could not reach the quiz backend. Is it running?');
  }
}

// ---- quiz-taking (quiz.html only) ----
let quizData = null;
let quizQuestionIndex = 0;
let quizCollectedAnswers = [];
let quizSelectedOption = null;

function loadQuizData() {
  const raw = sessionStorage.getItem('quizData');
  if (!raw) {
    // Nobody generated a quiz for this session — send them back rather
    // than show a broken empty page.
    window.location.href = 'role.html';
    return;
  }
  quizData = JSON.parse(raw);
  quizQuestionIndex = 0;
  quizCollectedAnswers = [];
  renderQuestion();
}

function renderQuestion() {
  const total = quizData.questions.length;
  const q = quizData.questions[quizQuestionIndex];
  quizSelectedOption = null;

  document.getElementById('quiz-tab').textContent = `Q${quizQuestionIndex + 1} / ${total}`;
  document.getElementById('quiz-skill').textContent = q.skill;
  document.getElementById('quiz-question').textContent = q.question;

  const optionsEl = document.getElementById('quiz-options');
  optionsEl.innerHTML = '';
  q.options.forEach(opt => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'opt';
    btn.innerHTML = '<span class="sq"></span>' + opt;
    btn.onclick = () => selectOption(btn, opt);
    optionsEl.appendChild(btn);
  });

  const fb = document.getElementById('quiz-feedback');
  fb.classList.remove('show', 'good', 'bad');
  fb.textContent = '';

  const nextBtn = document.getElementById('quiz-next');
  nextBtn.disabled = true;
  nextBtn.textContent = (quizQuestionIndex === total - 1) ? 'See my results' : 'Next question';
}

function selectOption(btn, optionText) {
  // Deliberately no right/wrong feedback here — the correct answer
  // stays server-side until the whole quiz is submitted and scored,
  // so someone can't just read the feedback to game the assessment.
  document.querySelectorAll('#quiz-options .opt').forEach(o => o.classList.remove('selected'));
  btn.classList.add('selected');
  quizSelectedOption = optionText;
  document.getElementById('quiz-next').disabled = false;
}

function nextQuestion() {
  const q = quizData.questions[quizQuestionIndex];
  quizCollectedAnswers.push({ question_id: q.id, selected_option: quizSelectedOption });

  if (quizQuestionIndex < quizData.questions.length - 1) {
    quizQuestionIndex++;
    renderQuestion();
  } else {
    sessionStorage.setItem('quizSubmission', JSON.stringify({
      attempt_id: quizData.attempt_id,
      answers: quizCollectedAnswers
    }));
    window.location.href = 'spin.html?step=scoring';
  }
}

// ---- results (results.html only) ----
function skillTier(scorePercent) {
  if (scorePercent >= 80) return { tag: 'STRONG', color: 'var(--teal)' };
  if (scorePercent >= 65) return { tag: 'SOLID', color: 'var(--teal)' };
  if (scorePercent >= 50) return { tag: 'GETTING THERE', color: 'var(--amber)' };
  return { tag: 'NEEDS WORK', color: 'var(--brick)' };
}

function renderResults() {
  const raw = sessionStorage.getItem('quizResults');
  if (!raw) {
    window.location.href = 'dashboard.html';
    return;
  }
  const results = JSON.parse(raw);
  quizTaken = true;
  readinessScore = Math.round(results.overall_score_percent);

  const numEl = document.getElementById('meter-num');
  const filled = Math.round(results.overall_score_percent / 20);
  for (let i = 1; i <= 5; i++) {
    const seg = document.getElementById('seg' + i);
    seg.style.width = (i <= filled) ? '100%' : '0%';
  }
  let n = 0;
  const target = Math.round(results.overall_score_percent);
  const t = setInterval(() => {
    n += 2;
    if (n >= target) { n = target; clearInterval(t); }
    numEl.textContent = n + '%';
  }, 22);

  const sorted = [...results.skills].sort((a, b) => b.score_percent - a.score_percent);
  const strongest = sorted[0];
  const weakest = sorted.slice(-2).map(s => s.skill);
  const msgEl = document.getElementById('results-message');
  if (strongest) {
    msgEl.querySelector('b').textContent = `You're strongest in ${strongest.skill}.`;
    msgEl.querySelector('span').textContent = weakest.length
      ? `Focus on ${weakest.join(' and ')} next — that's where the gap is biggest.`
      : '';
  }

  const listEl = document.getElementById('results-list');
  listEl.innerHTML = '';
  sorted.forEach((s, i) => {
    const tier = skillTier(s.score_percent);
    const row = document.createElement('div');
    row.className = 'lrow rise';
    row.style.animationDelay = (i * 0.05) + 's';
    row.innerHTML = `<span class="sq2" style="background:${tier.color};"></span><span class="lname">${s.skill}</span><span class="dots"></span><span class="lval">${Math.round(s.score_percent)}%</span><span class="ltag">${tier.tag}</span>`;
    listEl.appendChild(row);
  });

  // Accuracy card: highest-scoring skill vs. biggest gap, both from
  // THIS attempt specifically (not historical) — gap here is
  // required_level (0-10) converted to the same 0-100 scale as score_percent.
  const accScoreEl = document.getElementById('card-acc-score');
  if (accScoreEl) {
    accScoreEl.textContent = Math.round(results.overall_score_percent) + '%';
    document.getElementById('card-acc-badge').textContent = 'COMPLETED';

    const withGap = results.skills
      .filter(s => s.required_level !== null && s.required_level !== undefined)
      .map(s => ({ ...s, gapPercent: Math.max(0, s.required_level * 10 - s.score_percent) }));

    const highest = sorted[0];
    document.getElementById('card-hi-val').textContent = highest ? Math.round(highest.score_percent) + '%' : '—';
    document.getElementById('card-hi-bar').style.width = highest ? Math.round(highest.score_percent) + '%' : '0%';

    const biggestGap = withGap.length ? [...withGap].sort((a, b) => b.gapPercent - a.gapPercent)[0] : null;
    document.getElementById('card-lo-val').textContent = biggestGap ? Math.round(biggestGap.gapPercent) + '%' : '0%';
    document.getElementById('card-lo-bar').style.width = biggestGap ? Math.round(biggestGap.gapPercent) + '%' : '0%';
  }

  loadHistoryCards('card');
}

// ============================================================
// Shared attempt-history stats: powers the Completions/Streak cards
// on both results.html ("card-" prefixed ids) and the dashboard's
// Results tab ("dash-" prefixed ids), plus the dashboard's test
// history list and average-accuracy card (dashboard only).
// ============================================================
async function fetchAttemptHistory() {
  if (!currentUser || !currentUser.id) return null;
  const { data, error } = await supabaseClient
    .from('quiz_attempt_scores')
    .select('attempt_id, source, taken_at, score_percent, question_count')
    .eq('profile_id', currentUser.id)
    .order('taken_at', { ascending: true });
  if (error) {
    console.error('Failed to load attempt history:', error);
    return null;
  }
  return data || [];
}

function computeStreak(attempts) {
  const dateSet = new Set(attempts.map(a => new Date(a.taken_at).toDateString()));
  let streak = 0;
  const cursor = new Date();
  if (!dateSet.has(cursor.toDateString())) cursor.setDate(cursor.getDate() - 1);
  while (dateSet.has(cursor.toDateString())) {
    streak++;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

function renderStreakWeek(containerId, attempts) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const dateSet = new Set(attempts.map(a => new Date(a.taken_at).toDateString()));
  const labels = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  const today = new Date();
  const mondayOffset = (today.getDay() + 6) % 7;
  const monday = new Date(today);
  monday.setDate(today.getDate() - mondayOffset);

  container.innerHTML = '';
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const active = dateSet.has(d.toDateString());
    const isToday = d.toDateString() === today.toDateString();
    const span = document.createElement('span');
    span.textContent = labels[i];
    span.style.cssText = "flex:1; padding:4px 0; text-align:center; font-size:9.5px; font-family:'IBM Plex Mono',monospace; font-weight:700; border-radius:3px;";
    if (isToday && active) {
      span.style.background = 'var(--teal)'; span.style.color = '#fff';
    } else if (active) {
      span.style.background = 'var(--teal-soft)'; span.style.color = 'var(--teal)';
    } else {
      span.style.background = 'var(--card)'; span.style.border = '1px dashed var(--line)'; span.style.color = 'var(--slate)';
    }
    container.appendChild(span);
  }
}

function renderCompletionsBars(containerId, attempts) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';
  const recent = attempts.slice(-6);
  recent.forEach((a, i) => {
    const bar = document.createElement('div');
    const isLast = i === recent.length - 1;
    bar.style.cssText = `flex:1; height:${Math.max(a.score_percent, 4)}%; background:${isLast ? 'var(--gold, #D9A62E)' : 'var(--line)'}; border-radius:2px;`;
    container.appendChild(bar);
  });
}

function timeAgo(dateStr) {
  const diffDays = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000);
  if (diffDays <= 0) return 'today';
  if (diffDays === 1) return 'yesterday';
  return diffDays + ' days ago';
}

// prefix is 'card' (results.html) or 'dash' (dashboard) — only
// populates the Completions/Streak cards, since that's all
// results.html has. loadDashboardResultsTab() below handles the
// dashboard's extra Average card and history list.
async function loadHistoryCards(prefix) {
  const attempts = await fetchAttemptHistory();
  if (!attempts) return;

  const countEl = document.getElementById(prefix + '-completions-count');
  if (countEl) countEl.textContent = attempts.length;
  renderCompletionsBars(prefix + '-completions-bars', attempts);

  const streakDays = computeStreak(attempts);
  const daysEl = document.getElementById(prefix + '-streak-days');
  if (daysEl) daysEl.textContent = streakDays + (streakDays === 1 ? ' Day' : ' Days');
  const badgeEl = document.getElementById(prefix + '-streak-badge');
  if (badgeEl) {
    const today = new Date().toDateString();
    badgeEl.textContent = attempts.some(a => new Date(a.taken_at).toDateString() === today) ? '+1 TODAY' : 'ACTIVE';
  }
  renderStreakWeek(prefix + '-streak-week', attempts);

  return attempts;
}

async function loadDashboardResultsTab() {
  const attempts = await loadHistoryCards('dash');
  if (!attempts) return;

  const emptyHistoryEl = document.getElementById('dash-history-empty');
  const emptyProg = document.getElementById('dash-progress-empty');
  const fullProg = document.getElementById('dash-progress-full');

  if (attempts.length === 0) {
    if (emptyHistoryEl) emptyHistoryEl.style.display = 'block';
    if (emptyProg) emptyProg.style.display = 'block';
    if (fullProg) fullProg.style.display = 'none';
    return;
  }
  if (emptyHistoryEl) emptyHistoryEl.style.display = 'none';

  // 1. Average & Highlights Card
  const scores = attempts.map(a => a.score_percent);
  const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
  const hi = Math.max(...scores);
  const lo = Math.min(...scores);
  
  const avgScoreEl = document.getElementById('dash-avg-score');
  if (avgScoreEl) avgScoreEl.textContent = Math.round(avg) + '%';
  const hiValEl = document.getElementById('dash-avg-hi-val');
  if (hiValEl) hiValEl.textContent = Math.round(hi) + '%';
  const hiBarEl = document.getElementById('dash-avg-hi-bar');
  if (hiBarEl) hiBarEl.style.width = Math.round(hi) + '%';
  const loValEl = document.getElementById('dash-avg-lo-val');
  if (loValEl) loValEl.textContent = Math.round(lo) + '%';
  const loBarEl = document.getElementById('dash-avg-lo-bar');
  if (loBarEl) loBarEl.style.width = Math.round(lo) + '%';

  if (attempts.length >= 2) {
    const delta = attempts[attempts.length - 1].score_percent - attempts[attempts.length - 2].score_percent;
    const trendEl = document.getElementById('dash-avg-trend');
    if (trendEl) {
      trendEl.textContent = (delta >= 0 ? '▲ +' : '▼ ') + Math.abs(delta).toFixed(1) + '%';
      trendEl.style.color = delta >= 0 ? 'var(--teal)' : 'var(--brick)';
    }
  }

  // 2. Quiz History List
  const listEl = document.getElementById('dash-history-list');
  if (listEl) {
    listEl.innerHTML = '';
    const sourceLabels = { initial: 'Role Diagnostic', material: 'Uploaded Material', reassess: 'Re-assessment' };
    [...attempts].reverse().slice(0, 10).forEach(a => {
      const tier = a.score_percent >= 80
        ? { tag: 'PASSED', color: 'var(--teal)' }
        : a.score_percent >= 50
          ? { tag: 'REVIEW', color: 'var(--amber)' }
          : { tag: 'NEEDS WORK', color: 'var(--brick)' };
      const row = document.createElement('div');
      row.className = 'lrow';
      row.style.padding = '12px 6px';
      row.innerHTML = `<span class="sq2" style="background:${tier.color};"></span>
        <div style="display:flex; flex-direction:column; gap:2px;">
          <span class="lname" style="font-weight:600;">${sourceLabels[a.source] || a.source}</span>
          <span style="font-size:11px; color:var(--slate);">${a.question_count} questions · Completed ${timeAgo(a.taken_at)}</span>
        </div>
        <span class="dots"></span>
        <span class="lval mono">${Math.round(a.score_percent)}%</span>
        <span class="ltag mono" style="color:${tier.color};">${tier.tag}</span>`;
      listEl.appendChild(row);
    });
  }

  // 3. Progress Tab (Comparison across multiple attempts)
  const rowsEl = document.getElementById('dash-progress-rows');
  const bannerEl = document.getElementById('dash-progress-banner');

  if (attempts.length >= 2) {
    if (emptyProg) emptyProg.style.display = 'none';
    if (fullProg) fullProg.style.display = 'block';

    const first = attempts[0]; // Oldest attempt
    const latest = attempts[attempts.length - 1]; // Newest attempt
    const delta = Math.round(latest.score_percent - first.score_percent);

    if (rowsEl) {
      rowsEl.innerHTML = `
        <div class="compare-row" style="margin-top:14px;">
          <div class="cname">Overall Diagnostic Score</div>
          <div class="compare-vals">
            <span class="pill before">${Math.round(first.score_percent)}%</span>
            <span class="arrow">&rarr;</span>
            <span class="pill ${delta >= 0 ? 'after' : 'before'}">${Math.round(latest.score_percent)}%</span>
          </div>
        </div>
      `;
    }

    if (bannerEl) {
      bannerEl.innerHTML = delta >= 0
        ? `<div style="text-align:center;"><div class="badge-win">✓ GAINED +${delta}% SINCE FIRST ATTEMPT</div></div>`
        : `<div class="plain-msg"><b>Score dipped by ${Math.abs(delta)}%.</b> <span>Practice recommended on iGOT.</span></div>`;
    }
  } else {
    if (emptyProg) emptyProg.style.display = 'block';
    if (fullProg) fullProg.style.display = 'none';
  }
}

// ---- igot-courses.html: real course matches from skill_gaps ----
async function loadIgotCourses() {
  const loadingEl = document.getElementById('igot-loading');
  const emptyEl = document.getElementById('igot-empty');
  const listEl = document.getElementById('igot-course-list');

  if (!currentUser || !currentUser.id) {
    loadingEl.textContent = 'Sign in to see your recommendations.';
    return;
  }

  const { data: gaps, error: gapsError } = await supabaseClient
    .from('skill_gaps')
    .select('skill_id, skill_name, gap')
    .eq('profile_id', currentUser.id)
    .gt('gap', 0)
    .order('gap', { ascending: false });

  if (gapsError || !gaps || gaps.length === 0) {
    loadingEl.style.display = 'none';
    emptyEl.style.display = 'block';
    return;
  }

  const skillIds = gaps.map(g => g.skill_id);
  const { data: courseLinks, error: coursesError } = await supabaseClient
    .from('course_skills')
    .select('skill_id, courses(id, title, description, igot_link)')
    .in('skill_id', skillIds);

  if (coursesError || !courseLinks || courseLinks.length === 0) {
    loadingEl.style.display = 'none';
    emptyEl.style.display = 'block';
    emptyEl.querySelector('h3').textContent = 'No matching courses yet';
    emptyEl.querySelector('p').textContent = 'You have open gaps, but no course in the catalog covers them yet.';
    return;
  }

  const gapBySkillId = Object.fromEntries(gaps.map(g => [g.skill_id, g]));
  const courses = courseLinks
    .filter(l => l.courses)
    .map(l => ({
      title: l.courses.title,
      description: l.courses.description || '',
      igot_link: l.courses.igot_link || 'https://igotkarmayogi.gov.in/',
      skill_name: gapBySkillId[l.skill_id]?.skill_name || '',
      gap: gapBySkillId[l.skill_id]?.gap || 0
    }))
    .sort((a, b) => b.gap - a.gap)
    .slice(0, 6);

  const badges = [
    { label: 'PRIORITY FIX', bg: 'var(--brick)', color: '#fff' },
    { label: 'SKILL REFINEMENT', bg: 'var(--amber)', color: '#12181F' },
    { label: 'ADVANCED MODULE', bg: 'var(--teal)', color: '#fff' }
  ];

  listEl.innerHTML = '';
  courses.forEach((c, i) => {
    const badge = badges[i] || badges[badges.length - 1];
    const gapPercent = Math.round(c.gap * 10);
    const card = document.createElement('div');
    card.className = 'ledger course-card';
    card.style.margin = '0';
    card.innerHTML = `
      <div class="ledger-tab" style="background:${badge.bg}; color:${badge.color};">${badge.label}</div>
      <div class="num mono">COURSE ${String(i + 1).padStart(2, '0')} · IGOT PORTAL</div>
      <h3 style="font-size:18px; font-weight:700; margin-top:6px; font-family:'Space Grotesk',sans-serif;">${c.title}</h3>
      <p style="font-size:13px; color:var(--slate); margin-top:6px; line-height:1.5;">${c.description || 'On iGOT Karmayogi.'}</p>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:16px; flex-wrap:wrap; gap:10px;">
        <span class="course-tag mono">RESOLVES GAP: ${c.skill_name.toUpperCase()} (${gapPercent}%)</span>
        <a href="${c.igot_link}" target="_blank" rel="noopener noreferrer" class="btn btn-solid" style="padding:8px 16px; font-size:12px; text-decoration:none;">Open on iGOT &rarr;</a>
      </div>`;
    listEl.appendChild(card);
  });

  loadingEl.style.display = 'none';
  listEl.style.display = 'flex';
}


// ============================================================
// Dashboard Overview — LIVE QUIZ RESULTS FROM SUPABASE
// Uses the user's latest quiz attempt + skill_snapshots.
// ============================================================
async function loadDashboardOverviewTab() {
  if (!currentUser || !currentUser.id) return;

  const emptyOver = document.getElementById('dash-overview-empty');
  const fullOver = document.getElementById('dash-overview-full');

  const statReadyEl = document.getElementById('statReady');
  const statWeakEl = document.getElementById('statWeak');
  const statCoursesEl = document.getElementById('statCourses');

  // ----------------------------------------------------------
  // 1. Get the user's latest quiz attempt
  // ----------------------------------------------------------
  const { data: latestAttempt, error: attemptError } = await supabaseClient
    .from('quiz_attempts')
    .select('id, job_role_id, taken_at, source')
    .eq('profile_id', currentUser.id)
    .order('taken_at', { ascending: false })
    .limit(1)
    .maybeSingle();

  if (attemptError) {
    console.error('Failed to load latest quiz attempt:', attemptError);
  }

  // ----------------------------------------------------------
  // 2. Count total quizzes taken
  // ----------------------------------------------------------
  const { count: quizCount, error: countError } = await supabaseClient
    .from('quiz_attempts')
    .select('id', { count: 'exact', head: true })
    .eq('profile_id', currentUser.id);

  if (countError) {
    console.error('Failed to count quiz attempts:', countError);
  }

  if (statCoursesEl) {
    statCoursesEl.textContent = quizCount || 0;
  }

  // ----------------------------------------------------------
  // No quiz yet
  // ----------------------------------------------------------
  if (!latestAttempt) {
    if (emptyOver) emptyOver.style.display = 'block';
    if (fullOver) fullOver.style.display = 'none';

    if (statReadyEl) statReadyEl.textContent = '—';
    if (statWeakEl) statWeakEl.textContent = '—';

    return;
  }

  // ----------------------------------------------------------
  // 3. Get skill snapshots from THE LATEST QUIZ
  // ----------------------------------------------------------
  const { data: snapshots, error: snapshotError } = await supabaseClient
    .from('skill_snapshots')
    .select('skill_id, score, taken_at')
    .eq('profile_id', currentUser.id)
    .eq('attempt_id', latestAttempt.id);

  if (snapshotError) {
    console.error('Failed to load skill snapshots:', snapshotError);

    if (emptyOver) emptyOver.style.display = 'block';
    if (fullOver) fullOver.style.display = 'none';

    return;
  }

  if (!snapshots || snapshots.length === 0) {
    if (emptyOver) emptyOver.style.display = 'block';
    if (fullOver) fullOver.style.display = 'none';
    return;
  }

  // ----------------------------------------------------------
  // 4. Get skill names
  // ----------------------------------------------------------
  const skillIds = snapshots.map(s => s.skill_id);

  const { data: skillRows, error: skillError } = await supabaseClient
    .from('skills')
    .select('id, name')
    .in('id', skillIds);

  if (skillError) {
    console.error('Failed to load skill names:', skillError);
    return;
  }

  const skillNameById = Object.fromEntries(
    (skillRows || []).map(s => [s.id, s.name])
  );

  // ----------------------------------------------------------
  // 5. Get required levels for this user's role
  // ----------------------------------------------------------
  const { data: requiredRows, error: requiredError } = await supabaseClient
    .from('job_role_skills')
    .select('skill_id, required_level')
    .eq('job_role_id', latestAttempt.job_role_id)
    .in('skill_id', skillIds);

  if (requiredError) {
    console.error('Failed to load required skill levels:', requiredError);
  }

  const requiredBySkillId = Object.fromEntries(
    (requiredRows || []).map(r => [r.skill_id, r.required_level])
  );

  // ----------------------------------------------------------
  // 6. Build the LIVE overview skill dataset
  // ----------------------------------------------------------
  const skills = snapshots.map(snapshot => {
    const scorePercent = Math.round((snapshot.score || 0) * 10);
    const requiredLevel = requiredBySkillId[snapshot.skill_id];

    const requiredPercent =
      requiredLevel !== null &&
      requiredLevel !== undefined
        ? requiredLevel * 10
        : null;

    const gapPercent =
      requiredPercent !== null
        ? Math.max(0, requiredPercent - scorePercent)
        : 0;

    return {
      id: snapshot.skill_id,
      name: skillNameById[snapshot.skill_id] || 'Unknown skill',
      score: scorePercent,
      required: requiredPercent,
      gap: gapPercent
    };
  });

  // ----------------------------------------------------------
  // 7. Calculate role readiness
  // ----------------------------------------------------------
  const readinessValues = skills
    .filter(s => s.required !== null && s.required > 0)
    .map(s => Math.min(100, (s.score / s.required) * 100));

  const readyPercent = readinessValues.length
    ? Math.round(
        readinessValues.reduce((sum, value) => sum + value, 0) /
        readinessValues.length
      )
    : Math.round(
        skills.reduce((sum, s) => sum + s.score, 0) /
        skills.length
      );

  // Skills below their required level
  const gapsFound = skills.filter(s =>
    s.required !== null && s.score < s.required
  ).length;

  // Strong skills
  const strongSkills = skills.filter(s => s.score >= 70);

  // ----------------------------------------------------------
  // 8. Show full Overview
  // ----------------------------------------------------------
  if (emptyOver) emptyOver.style.display = 'none';
  if (fullOver) fullOver.style.display = 'block';

  if (statReadyEl) {
    statReadyEl.textContent = readyPercent + '%';
  }

  if (statWeakEl) {
    statWeakEl.textContent = gapsFound;
  }

  // ----------------------------------------------------------
  // 9. Legacy meter — keep it working
  // ----------------------------------------------------------
  const meterNum = document.getElementById('dashMeterNum');

  if (meterNum) {
    meterNum.textContent = readyPercent + '%';
  }

  const filled = Math.round(readyPercent / 20);

  for (let i = 1; i <= 5; i++) {
    const segment = document.getElementById('dash-seg' + i);

    if (segment) {
      segment.style.width =
        (i <= filled) ? '100%' : '0%';
    }
  }

  // ----------------------------------------------------------
  // 10. Build skill list used by Premium Overview
  // ----------------------------------------------------------
  const listEl = document.getElementById('dash-overview-list');

  if (listEl) {
    listEl.innerHTML = '';

    const sortedSkills = [...skills]
      .sort((a, b) => b.score - a.score);

    sortedSkills.forEach(skill => {
      const tier = skillTier(skill.score);

      const row = document.createElement('div');
      row.className = 'lrow';

      row.innerHTML = `
        <span
          class="sq2"
          style="background:${tier.color};"
        ></span>

        <span class="lname">
          ${skill.name}
        </span>

        <span class="dots"></span>

        <span class="lval mono">
          ${skill.score}%
        </span>

        <span class="ltag mono">
          ${tier.tag}
        </span>
      `;

      listEl.appendChild(row);
    });
  }

  // ----------------------------------------------------------
  // 11. Premium Overview stats
  // ----------------------------------------------------------
  const strongStat = document.getElementById('ov-stat-strong');

  if (strongStat) {
    strongStat.textContent = strongSkills.length;
  }

  // ----------------------------------------------------------
  // 12. Premium Overview insight
  // ----------------------------------------------------------
  const strongest = [...skills]
    .sort((a, b) => b.score - a.score)[0];

  const weakest = [...skills]
    .sort((a, b) => b.gap - a.gap)[0];

  const insightTitle = document.getElementById('ov-insight-title');
  const insightText = document.getElementById('ov-insight-text');

  if (insightTitle && insightText) {
    if (strongest && weakest && weakest.gap > 0) {
      insightTitle.textContent =
        `${strongest.name} is your strongest area.`;

      insightText.textContent =
        `${weakest.name} is currently your biggest development opportunity. Focus your next practice session there.`;
    } else if (strongest) {
      insightTitle.textContent =
        `${strongest.name} is your strongest area.`;

      insightText.textContent =
        `You're currently meeting the required level across your assessed skills.`;
    }
  }

  // ----------------------------------------------------------
  // 13. Up Next — based on the biggest REAL skill gap
  // ----------------------------------------------------------
  const openGaps = skills
    .filter(s => s.gap > 0)
    .sort((a, b) => b.gap - a.gap);

  const upNextCard = document.getElementById('dash-upnext-card');

  if (upNextCard) {
    upNextCard.style.display = 'none';
  }

  if (openGaps.length > 0) {
    const { data: courseLinks, error: courseError } =
      await supabaseClient
        .from('course_skills')
        .select('skill_id, courses(title, description)')
        .in(
          'skill_id',
          openGaps.map(s => s.id)
        );

    if (courseError) {
      console.error('Failed to load Overview course recommendation:', courseError);
    }

    const gapBySkillId = Object.fromEntries(
      openGaps.map(s => [s.id, s])
    );

    const best = (courseLinks || [])
      .filter(link => link.courses)
      .sort(
        (a, b) =>
          (gapBySkillId[b.skill_id]?.gap || 0) -
          (gapBySkillId[a.skill_id]?.gap || 0)
      )[0];

    if (best && upNextCard) {
      upNextCard.style.display = 'block';

      const titleEl = document.getElementById('dash-upnext-title');
      const metaEl = document.getElementById('dash-upnext-meta');
      const tagEl = document.getElementById('dash-upnext-tag');

      if (titleEl) {
        titleEl.textContent = best.courses.title;
      }

      if (metaEl) {
        metaEl.textContent =
          best.courses.description || 'On iGOT Karmayogi';
      }

      if (tagEl) {
        tagEl.textContent =
          'FIXES: ' +
          (gapBySkillId[best.skill_id]?.name || '').toUpperCase();
      }
    }
  }

  // ----------------------------------------------------------
  // 14. Tell Premium Overview to refresh immediately
  // ----------------------------------------------------------
  if (typeof window.refreshPremiumOverview === 'function') {
    window.refreshPremiumOverview();
  }
}

// ---- practice: real course recommendations from skill_gaps (practice.html only) ----
let recommendedCourses = [];
let recommendedIndex = 0;

async function loadRecommendedCourses() {
  const loadingEl = document.getElementById('practice-loading');
  const emptyEl = document.getElementById('practice-empty');
  const contentEl = document.getElementById('practice-content');

  if (!currentUser || !currentUser.id) {
    loadingEl.textContent = 'Sign in to see your recommendations.';
    return;
  }

  // Worst gap first — this is the single source of truth for "where is
  // this person behind," computed by the skill_gaps view from their
  // latest quiz scores vs. their role's required levels.
  const { data: gaps, error: gapsError } = await supabaseClient
    .from('skill_gaps')
    .select('skill_id, skill_name, gap')
    .eq('profile_id', currentUser.id)
    .gt('gap', 0)
    .order('gap', { ascending: false });

  if (gapsError) {
    console.error('Failed to load skill gaps:', gapsError);
    loadingEl.textContent = "Couldn't load your recommendations right now.";
    return;
  }

  if (!gaps || gaps.length === 0) {
    loadingEl.style.display = 'none';
    emptyEl.style.display = 'block';
    return;
  }

  const skillIds = gaps.map(g => g.skill_id);
  const { data: courseLinks, error: coursesError } = await supabaseClient
    .from('course_skills')
    .select('skill_id, courses(id, title, description, igot_link)')
    .in('skill_id', skillIds);

  if (coursesError || !courseLinks || courseLinks.length === 0) {
    console.error('Failed to load matching courses:', coursesError);
    loadingEl.style.display = 'none';
    emptyEl.style.display = 'block';
    emptyEl.querySelector('h3').textContent = 'No matching courses yet';
    emptyEl.querySelector('p').textContent = 'You have open gaps, but no course in the catalog covers them yet.';
    return;
  }

  // Order courses by how bad the gap is for the skill they address —
  // a course fixing your worst gap should show up first.
  const gapBySkillId = Object.fromEntries(gaps.map(g => [g.skill_id, g]));
  recommendedCourses = courseLinks
    .filter(link => link.courses)
    .map(link => ({
      title: link.courses.title,
      description: link.courses.description || '',
      igot_link: link.courses.igot_link || '',
      skill_name: gapBySkillId[link.skill_id]?.skill_name || '',
      gap: gapBySkillId[link.skill_id]?.gap || 0
    }))
    .sort((a, b) => b.gap - a.gap);

  recommendedIndex = 0;
  loadingEl.style.display = 'none';
  contentEl.style.display = 'block';
  renderRecommendedCourse();
}

function renderRecommendedCourse() {
  const c = recommendedCourses[recommendedIndex];
  document.getElementById('course-num').textContent = `${recommendedIndex + 1} / RECOMMENDED (${recommendedCourses.length})`;
  document.getElementById('course-title').textContent = c.title;
  document.getElementById('course-meta').textContent = c.description || 'On iGOT Karmayogi';
  document.getElementById('course-tag').textContent = 'FIXES: ' + c.skill_name.toUpperCase();
}

function nextCourse() {
  if (recommendedCourses.length === 0) return;
  recommendedIndex = (recommendedIndex + 1) % recommendedCourses.length;
  const card = document.getElementById('course-card');
  card.style.opacity = '0';
  card.style.transform = 'translateY(5px)';
  card.style.transition = 'opacity .15s ease, transform .15s ease';
  setTimeout(() => {
    renderRecommendedCourse();
    card.style.opacity = '1';
    card.style.transform = 'translateY(0)';
  }, 160);
}

function openCurrentCourse() {
  const c = recommendedCourses[recommendedIndex];
  if (c && c.igot_link) {
    window.open(c.igot_link, '_blank');
  } else {
    goScreen('progress');
  }
}

// ============================================================
// Signup wizard (signup.html only — kept as one file, see header note)
// ============================================================
let signupCurrent = 0;
const signupSteps = ['signup-1', 'signup-2', 'signup-3', 'signup-4', 'signup-review', 'signup-success'];

function showSignupStep(name) {
  document.querySelectorAll('#app .screen').forEach(s => s.classList.remove('active'));
  const el = document.getElementById('screen-' + name);
  if (el) el.classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---- ministry / job role dropdowns (signup.html step 2 only) ----
async function loadMinistryAndRoleDropdowns() {
  const ministrySelect = document.getElementById('f-ministry');
  const roleSelect = document.getElementById('f-desig');
  if (!ministrySelect || !roleSelect) return;

  const [{ data: ministries, error: ministryError }, { data: jobRoles, error: roleError }] = await Promise.all([
    supabaseClient.from('ministries').select('id, name').order('name'),
    supabaseClient.from('job_roles').select('id, name').order('name')
  ]);

  if (ministryError || !ministries) {
    console.error('Could not load ministries:', ministryError);
    ministrySelect.innerHTML = '<option value="">Could not load ministries</option>';
  } else {
    ministrySelect.innerHTML = '<option value="">Select one</option>' +
      ministries.map(m => `<option value="${m.id}">${m.name}</option>`).join('');
  }

  if (roleError || !jobRoles) {
    console.error('Could not load job roles:', roleError);
    roleSelect.innerHTML = '<option value="">Could not load job roles</option>';
  } else {
    roleSelect.innerHTML = '<option value="">Select one</option>' +
      jobRoles.map(r => `<option value="${r.id}">${r.name}</option>`).join('');
  }
}
loadMinistryAndRoleDropdowns();

function showFieldError(inputId, errId, show) {
  document.getElementById(inputId).classList.toggle('err', show);
  document.getElementById(errId).classList.toggle('show', show);
}

function togglePw(id, btn) {
  const el = document.getElementById(id);
  const isPw = el.type === 'password';
  el.type = isPw ? 'text' : 'password';
  btn.textContent = isPw ? 'HIDE' : 'SHOW';
}

function checkPwStrength() {
  const v = document.getElementById('f-pass').value;
  let score = 0;
  if (v.length >= 8) score++;
  if (/[A-Z]/.test(v) && /[0-9]/.test(v)) score++;
  if (/[^A-Za-z0-9]/.test(v) && v.length >= 10) score++;
  ['pw1', 'pw2', 'pw3'].forEach((id, i) => {
    document.getElementById(id).className = i < score ? ('on' + score) : '';
  });
}

function validateStep1() {
  let ok = true;
  const name = document.getElementById('f-name').value.trim();
  const email = document.getElementById('f-email').value.trim();
  const pass = document.getElementById('f-pass').value;
  const pass2 = document.getElementById('f-pass2').value;
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

  showFieldError('f-name', 'err-name', name === ''); if (name === '') ok = false;
  showFieldError('f-email', 'err-email', !emailOk); if (!emailOk) ok = false;
  showFieldError('f-pass', 'err-pass', pass.length < 8); if (pass.length < 8) ok = false;
  showFieldError('f-pass2', 'err-pass2', pass2 !== pass || pass2 === ''); if (pass2 !== pass || pass2 === '') ok = false;
  return ok;
}

function validateStep2() {
  let ok = true;
  const ministry = document.getElementById('f-ministry').value.trim();
  const desig = document.getElementById('f-desig').value.trim();
  const years = document.getElementById('f-years').value;
  const yearsOk = years !== '' && Number(years) >= 0 && Number(years) <= 50;

  showFieldError('f-ministry', 'err-ministry', ministry === ''); if (ministry === '') ok = false;
  showFieldError('f-desig', 'err-desig', desig === ''); if (desig === '') ok = false;
  showFieldError('f-years', 'err-years', !yearsOk); if (!yearsOk) ok = false;
  return ok;
}

function validateStep3() {
  let ok = true;
  const qual = document.getElementById('f-qual').value;
  const field = document.getElementById('f-field').value.trim();
  showFieldError('f-qual', 'err-qual', qual === ''); if (qual === '') ok = false;
  showFieldError('f-field', 'err-field', field === ''); if (field === '') ok = false;
  return ok;
}

function shakeCurrent() {
  const el = document.getElementById('screen-' + signupSteps[signupCurrent]);
  el.classList.remove('shake'); void el.offsetWidth; el.classList.add('shake');
}

function goStep(dir) {
  if (dir === 1 && !validateStep1()) { shakeCurrent(); return; }
  if (dir === 2 && !validateStep2()) { shakeCurrent(); return; }
  if (dir === 3 && !validateStep3()) { shakeCurrent(); return; }
  signupCurrent += (dir > 0 ? 1 : dir);
  showSignupStep(signupSteps[signupCurrent]);
}

// ---- iGOT course chips (signup.html only) ----
let selectedCourses = [];
let noneDone = false;
const chipGrid = document.getElementById('course-chips');

async function loadCourseChips() {
  if (!chipGrid) return;
  const { data: courses, error } = await supabaseClient.from('courses').select('id, title').order('title');
  if (error || !courses) {
    console.error('Could not load courses:', error);
    chipGrid.innerHTML = '<p class="note">Could not load the course list. You can skip this step.</p>';
    return;
  }
  chipGrid.innerHTML = '';
  courses.forEach(course => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'chip';
    el.innerHTML = `<span class="dot"></span>${course.title}`;
    el.onclick = () => {
      if (noneDone) toggleNone();
      el.classList.toggle('selected');
      if (el.classList.contains('selected')) selectedCourses.push(course.title);
      else selectedCourses = selectedCourses.filter(c => c !== course.title);
    };
    chipGrid.appendChild(el);
  });
}
loadCourseChips();


function toggleNone() {
  noneDone = !noneDone;
  const btn = document.getElementById('none-toggle');
  if (noneDone) {
    selectedCourses = [];
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('selected'));
    chipGrid.style.opacity = '.4';
    chipGrid.style.pointerEvents = 'none';
    btn.style.color = 'var(--teal)';
    btn.textContent = "✓ Noted — you're just starting out";
  } else {
    chipGrid.style.opacity = '1';
    chipGrid.style.pointerEvents = 'auto';
    btn.style.color = '';
    btn.textContent = "I haven't completed any yet";
  }
}

// ---- review ----
function showReview() {
  const box = document.getElementById('review-box');
  const courseText = noneDone ? "None yet" : (selectedCourses.length ? selectedCourses.join(', ') : "None selected");
  const rows = [
    ['Name', document.getElementById('f-name').value.trim()],
    ['Email', document.getElementById('f-email').value.trim()],
    ['Ministry / Dept.', document.getElementById('f-ministry').selectedOptions[0]?.text || ''],
    ['Designation', document.getElementById('f-desig').selectedOptions[0]?.text || ''],
    ['Years in role', document.getElementById('f-years').value],
    ['Qualification', document.getElementById('f-qual').value],
    ['Field of study', document.getElementById('f-field').value.trim()],
    ['iGOT courses done', courseText]
  ];
  box.innerHTML = '<div class="ledger-tab">REVIEW</div>' +
    rows.map(([k, v]) => `<div class="rev-row"><span class="rk">${k}</span><span class="rv">${v || '—'}</span></div>`).join('');
  showSignupStep('signup-review');
}

// ---- Supabase: real auth signup + profile row ----
async function createAccount() {
  const btn = document.getElementById('create-account-btn');
  const name = document.getElementById('f-name').value.trim();
  const email = document.getElementById('f-email').value.trim();
  const password = document.getElementById('f-pass').value;
  const ministryId = document.getElementById('f-ministry').value || null;
  const jobRoleId = document.getElementById('f-desig').value || null;
  const years = Number(document.getElementById('f-years').value);
  const qual = document.getElementById('f-qual').value;
  const field = document.getElementById('f-field').value.trim();
  const courses = noneDone ? [] : selectedCourses;

  if (btn) { btn.disabled = true; btn.textContent = 'Creating account…'; }

  // Step 1: create the actual auth user (this is what lets them log back in later)
  const { data: signUpData, error: signUpError } = await supabaseClient.auth.signUp({
    email: email,
    password: password
  });

  if (signUpError) {
    console.error('Auth signup failed:', signUpError);
    if (btn) { btn.disabled = false; btn.textContent = 'Create account'; }
    alert(signUpError.message || 'Something went wrong creating your account. Please try again.');
    return;
  }

  const userId = signUpData.user ? signUpData.user.id : null;
  if (!userId) {
    if (btn) { btn.disabled = false; btn.textContent = 'Create account'; }
    alert('Account created, but something went wrong linking your profile. Please contact support.');
    return;
  }

  // Step 2: insert the profile row, keyed to the new auth user's id
  const { error: profileError } = await supabaseClient.from('profiles').insert({
    id: userId,
    full_name: name,
    ministry_id: ministryId,
    job_role_id: jobRoleId,
    years_in_role: years,
    qualification: qual,
    field_of_study: field,
    igot_courses: courses
  });

  if (btn) { btn.disabled = false; btn.textContent = 'Create account'; }

  if (profileError) {
    console.error('Profile save failed:', profileError);
    alert('Your account was created, but saving your profile details failed. Please try logging in and updating your profile.');
    return;
  }

  const thanksName = document.getElementById('thanks-name');
  if (thanksName) thanksName.textContent = name.split(' ')[0] || 'there';
  showSignupStep('signup-success');
}

/* ==========================================================
   PREMIUM OVERVIEW — DYNAMIC DATA
   ========================================================== */

(function initPremiumOverview(){

  function updatePremiumOverview(){

    const readyEl = document.getElementById("statReady");
    const weakEl = document.getElementById("statWeak");
    const coursesEl = document.getElementById("statCourses");

    if (!readyEl) return;

    const ready = parseInt((readyEl.textContent || "0").replace(/\D/g, "")) || 0;
    const weak = parseInt((weakEl?.textContent || "0").replace(/\D/g, "")) || 0;
    const courses = parseInt((coursesEl?.textContent || "0").replace(/\D/g, "")) || 0;

    /* ---------- HERO ---------- */

    const readyBig = document.getElementById("ov-ready-big");
    const readyStat = document.getElementById("ov-stat-ready");
    const gapsStat = document.getElementById("ov-stat-gaps");
    const strongStat = document.getElementById("ov-stat-strong");
    const quizzesStat = document.getElementById("ov-stat-quizzes");

    if (readyBig) readyBig.textContent = ready + "%";
    if (readyStat) readyStat.textContent = ready + "%";
    if (gapsStat) gapsStat.textContent = weak;
    if (quizzesStat) quizzesStat.textContent = courses;

    /* ---------- READINESS RING ---------- */

    const ring = document.getElementById("ov-ring-progress");

    if (ring){
      const circumference = 377;
      const offset = circumference - (Math.max(0, Math.min(100, ready)) / 100) * circumference;

      ring.style.strokeDasharray = circumference;
      ring.style.strokeDashoffset = offset;
    }

    /* ---------- STATUS ---------- */

    const statusText = document.getElementById("ov-status-text");

    if (statusText){
      if (ready >= 80){
        statusText.textContent = "ROLE READY";
      } else if (ready >= 60){
        statusText.textContent = "ON TRACK";
      } else if (ready >= 40){
        statusText.textContent = "DEVELOPING";
      } else {
        statusText.textContent = "BUILDING FOUNDATION";
      }
    }

    /* ---------- STAT LINES ---------- */

    const readyLine = document.getElementById("ov-ready-line");
    const gapLine = document.getElementById("ov-gap-line");
    const strongLine = document.getElementById("ov-strong-line");
    const quizLine = document.getElementById("ov-quiz-line");

    if (readyLine) readyLine.style.setProperty("--stat-width", ready + "%");
    if (gapLine) gapLine.style.setProperty("--stat-width", Math.min(100, weak * 15) + "%");
    if (strongLine) strongLine.style.setProperty("--stat-width", "70%");
    if (quizLine) quizLine.style.setProperty("--stat-width", Math.min(100, courses * 10) + "%");

    /* ---------- READ SKILLS ---------- */

    const skillList = document.getElementById("dash-overview-list");

    if (!skillList) return;

    const rows = [...skillList.querySelectorAll(".lrow")];

    const skills = rows.map(row => {

      const nameEl = row.querySelector(".lname");
      const valueEl = row.querySelector(".lval");

      const name = nameEl
        ? nameEl.textContent.trim()
        : "Skill";

      const value = parseInt(
        (valueEl?.textContent || "0").replace(/\D/g, "")
      ) || 0;

      return {
        name,
        value
      };

    }).filter(skill => skill.name);

    /* ---------- STRONG / DEVELOPING / WEAK ---------- */

    const strong = skills.filter(s => s.value >= 70);
    const developing = skills.filter(s => s.value >= 50 && s.value < 70);
    const weakSkills = skills.filter(s => s.value < 50);

    if (strongStat){
      strongStat.textContent = strong.length;
    }

    /* ---------- SKILL BAR WIDTHS ---------- */

    rows.forEach(row => {

      const valueEl = row.querySelector(".lval");

      if (!valueEl) return;

      const value = parseInt(
        valueEl.textContent.replace(/\D/g, "")
      ) || 0;

      row.style.setProperty(
        "--skill-width",
        Math.max(3, Math.min(100, value)) + "%"
      );

    });

    /* ---------- HEALTH DONUT ---------- */

    const donut = document.getElementById("ov-health-donut");

    const strongCount = strong.length;
    const developingCount = developing.length;
    const weakCount = weakSkills.length;
    const total = skills.length || 1;

    if (donut){

      const strongDeg = (strongCount / total) * 360;
      const developingDeg = (developingCount / total) * 360;

      donut.style.background = `
        conic-gradient(
          var(--teal) 0deg ${strongDeg}deg,
          var(--amber) ${strongDeg}deg ${strongDeg + developingDeg}deg,
          var(--brick) ${strongDeg + developingDeg}deg 360deg
        )
      `;
    }

    const healthPercent = document.getElementById("ov-health-percent");

    if (healthPercent){
      healthPercent.textContent = ready + "%";
    }

    const strongLabel = document.getElementById("ov-strong-label");
    const developingLabel = document.getElementById("ov-developing-label");
    const weakLabel = document.getElementById("ov-weak-label");

    if (strongLabel) strongLabel.textContent = strongCount + " skills";
    if (developingLabel) developingLabel.textContent = developingCount + " skills";
    if (weakLabel) weakLabel.textContent = weakCount + " skills";

    /* ---------- PRIORITY AREAS ---------- */

    const focusList = document.getElementById("ov-focus-list");

    if (focusList){

      const priorities = [...skills]
        .sort((a,b) => a.value - b.value)
        .slice(0,3);

      if (priorities.length){

        focusList.innerHTML = priorities.map((skill, index) => {

          let description = "Needs improvement";

          if (skill.value >= 50){
            description = "Strengthen this skill further";
          } else if (skill.value < 30){
            description = "High-priority development area";
          }

          return `
            <div class="ov-focus-item">

              <div class="ov-focus-number">
                0${index + 1}
              </div>

              <div>
                <div class="ov-focus-title">
                  ${skill.name}
                </div>

                <div class="ov-focus-description">
                  ${description}
                </div>

                <div class="ov-focus-track">
                  <i style="width:${Math.max(3, skill.value)}%"></i>
                </div>
              </div>

              <div class="ov-focus-score">
                ${skill.value}%
              </div>

            </div>
          `;

        }).join("");

      } else {

        focusList.innerHTML = `
          <div class="ov-focus-description">
            Complete a quiz to identify your priority areas.
          </div>
        `;

      }
    }

    /* ---------- PERSONALIZED INSIGHT ---------- */

    const insightTitle = document.getElementById("ov-insight-title");
    const insightText = document.getElementById("ov-insight-text");

    const strongest = [...skills].sort((a,b) => b.value - a.value)[0];
    const weakest = [...skills].sort((a,b) => a.value - b.value)[0];

    if (insightTitle && insightText){

      if (strongest && weakest){

        insightTitle.textContent =
          strongest.name + " is your strongest area.";

        insightText.textContent =
          weakest.name +
          " is currently your biggest development opportunity. Focus your next practice session there.";

      } else {

        insightTitle.textContent = "Keep building your profile.";

        insightText.textContent =
          "Complete more assessments to unlock personalized skill insights.";

      }
    }

    /* ---------- HERO SUPPORTING TEXT ---------- */

    const readyLineText = document.getElementById("ov-ready-line");
    const gapLineText = document.getElementById("ov-gap-line");
    const strongLineText = document.getElementById("ov-strong-line");
    const quizLineText = document.getElementById("ov-quiz-line");

    if (readyLineText) readyLineText.style.setProperty("--stat-width", ready + "%");
    if (gapLineText) gapLineText.style.setProperty("--stat-width", Math.min(100, weak * 15) + "%");
    if (strongLineText) strongLineText.style.setProperty("--stat-width", Math.min(100, strong.length * 15) + "%");
    if (quizLineText) quizLineText.style.setProperty("--stat-width", Math.min(100, courses * 10) + "%");

  }


  window.refreshPremiumOverview = updatePremiumOverview;

  /* Run once immediately */
  updatePremiumOverview();


  /* Run again whenever the existing dashboard skill list changes */
  const skillList = document.getElementById("dash-overview-list");

  if (skillList){

    const observer = new MutationObserver(() => {
      updatePremiumOverview();
    });

    observer.observe(skillList, {
      childList: true,
      subtree: true,
      characterData: true
    });

  }

})();

// ---- run page-specific setup ----
initPage();
