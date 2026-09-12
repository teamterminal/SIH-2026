// admin.html only.
//
// This file just DEFINES initAdminPage() below — it doesn't call
// supabaseClient, currentUser, or BACKEND_URL at the top level, so it's
// safe for this file to load before app.js (which is where those are
// actually created). app.js calls initAdminPage() itself, once it has
// finished checking the session and building currentUser, from inside
// its initPage() function.

async function initAdminPage() {
  const deniedEl = document.getElementById('adminDenied');
  const loadingEl = document.getElementById('adminSkillLoading');
  const emptyEl = document.getElementById('adminSkillEmpty');
  const errorEl = document.getElementById('adminSkillError');
  const contentEl = document.getElementById('adminSkillContent');
  const chartEl = document.getElementById('adminSkillChart');
  const tableBodyEl = document.getElementById('adminSkillTableBody');
  const scopeSubtextEl = document.getElementById('adminScopeSubtext');

  const showOnly = (el) => {
    [deniedEl, loadingEl, emptyEl, errorEl, contentEl].forEach(e => { if (e) e.style.display = 'none'; });
    if (el) el.style.display = 'block';
  };

  // Frontend-side check purely for a clean message — the backend enforces
  // this for real by checking the caller's own session, so this is not
  // the security boundary, just better UX than a raw 403 in the console.
  if (!currentUser || currentUser.adminScope === 'none') {
    showOnly(deniedEl);
    return;
  }

  showOnly(loadingEl);

  try {
    const { data: { session } } = await supabaseClient.auth.getSession();
    if (!session) { showOnly(deniedEl); return; }

    const res = await fetch(BACKEND_URL + '/admin/skill-gaps', {
      headers: { 'Authorization': 'Bearer ' + session.access_token }
    });

    if (res.status === 401 || res.status === 403) { showOnly(deniedEl); return; }
    if (!res.ok) { showOnly(errorEl); return; }

    const data = await res.json();

    if (scopeSubtextEl) {
      scopeSubtextEl.textContent = data.scope === 'global' ? 'across all ministries' : 'across your ministry';
    }

    if (!data.skills || data.skills.length === 0) { showOnly(emptyEl); return; }

    if (chartEl) {
      chartEl.innerHTML = data.skills.map(s => {
        const pct = Math.max(4, (s.average_score / 10) * 100); // small floor so a 0 still shows a sliver
        const barColor = s.average_score < 5 ? 'var(--gold, #D9A62E)' : 'var(--teal)';
        return `
          <div style="margin-bottom:14px;">
            <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px;">
              <span>${escapeHtml(s.skill)}</span>
              <span style="font-family:'IBM Plex Mono',monospace; color:var(--slate);">${s.average_score.toFixed(1)}/10 · ${s.officer_count} officer${s.officer_count === 1 ? '' : 's'}</span>
            </div>
            <div style="background:var(--line); border-radius:4px; height:10px; overflow:hidden;">
              <div style="width:${pct}%; height:100%; background:${barColor};"></div>
            </div>
          </div>`;
      }).join('');
    }

    if (tableBodyEl) {
      tableBodyEl.innerHTML = data.skills.map(s => `
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:10px 14px;">${escapeHtml(s.skill)}</td>
          <td style="padding:10px 14px;">${s.average_score.toFixed(1)}</td>
          <td style="padding:10px 14px;">${s.officer_count}</td>
        </tr>`).join('');
    }

    showOnly(contentEl);
  } catch (err) {
    console.error('Could not load admin skill gaps:', err);
    showOnly(errorEl);
  }
}

// Skill names come from your own seeded `skills` table, so this is just a
// safety habit rather than a real defense against untrusted input here.
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
