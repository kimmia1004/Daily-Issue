/* 데일리 이슈 — 렌더러 (바닐라 JS, 빌드 불필요)
 *
 *   data/manifest.js     window.DAILY.manifest = ['2026-10-01', '2026-10-02', ...]   (오래된 호 → 최신 호)
 *   data/YYYY-MM-DD.js   window.DAILY.editions['YYYY-MM-DD'] = { front, tracking, briefs, ... }
 *
 * index.html 은 주소 해시(#2026-10-02)로 호를 고르고, 없으면 가장 최신 호를 보여줍니다.
 */
(function () {
  'use strict';

  var SITE = { name: '데일리 이슈', en: 'The Daily Issue', sub: '오늘의 시사, 5분 브리핑' };
  var D = (window.DAILY = window.DAILY || {});
  D.editions = D.editions || {};
  var app = document.getElementById('app');
  var WD = ['일', '월', '화', '수', '목', '금', '토'];
  var CHARS_PER_MIN = 450; // 공백 제외 글자 수 기준 읽기 속도

  /* ── 유틸 ─────────────────────────────────────────── */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function parts(s) {
    var m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(s || '');
    return m ? { y: +m[1], m: +m[2], d: m[3] ? +m[3] : 0 } : null;
  }
  function toDate(s) { var p = parts(s); return p ? new Date(p.y, p.m - 1, p.d || 1) : null; }
  function fmtLong(s) { var d = toDate(s); return d.getFullYear() + '년 ' + (d.getMonth() + 1) + '월 ' + d.getDate() + '일 ' + WD[d.getDay()] + '요일'; }
  function fmtDot(s) { var p = parts(s); return p.y + '.' + (p.m < 10 ? '0' : '') + p.m + '.' + (p.d < 10 ? '0' : '') + p.d; }
  function fmtMD(s) { var p = parts(s); return !p ? s : (p.d ? p.m + '.' + p.d : p.m + '월'); }
  function daysBetween(a, b) { return Math.round((toDate(b) - toDate(a)) / 86400000); }
  function len(s) { return s ? String(s).replace(/\s+/g, '').length : 0; }

  /* ── 컴포넌트 ─────────────────────────────────────── */
  function photo(it, ratio, eager) {
    var im = it.image || {};
    var label = '원문 기사 보기 — ' + it.headline + ' (' + it.source + ')';
    var style = '--ar:' + ratio + (im.pos ? ';--pos:' + esc(im.pos) : '');
    return '<a class="ph" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer" aria-label="' + esc(label) + '">' +
      '<span class="ht' + (im.src ? '' : ' noimg') + '" style="' + style + '" data-src="' + esc(it.source) + '">' +
      (im.src ? '<img src="' + esc(im.src) + '" alt="' + esc(im.alt || '') + '" loading="' + (eager ? 'eager' : 'lazy') + '" decoding="async" referrerpolicy="no-referrer">' : '') +
      '</span>' +
      '<span class="credit">' + esc(im.credit || it.source) + ' <i aria-hidden="true">↗</i></span></a>';
  }
  function headline(it, tag, cls) {
    return '<' + tag + ' class="hl ' + (cls || '') + '"><a href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">' + esc(it.headline) + '</a></' + tag + '>';
  }
  function more(list) {
    if (!list || !list.length) return '';
    return '<p class="more"><b>함께 보기</b>' + list.map(function (m) {
      return '<a href="' + esc(m.url) + '" target="_blank" rel="noopener noreferrer"' + (m.title ? ' title="' + esc(m.title) + '"' : '') + '>' + esc(m.source) + '</a>';
    }).join('<span class="sep">·</span>') + '</p>';
  }
  function why(it) { return it.why ? '<p class="why"><b>알아둘 점</b>' + esc(it.why) + '</p>' : ''; }

  function facts(it) {
    if (!it.facts || !it.facts.length) return '';
    return '<aside class="facts"><h4>' + esc(it.factsTitle || '한눈에 보기') + '</h4><dl>' + it.facts.map(function (f) {
      return '<div><dt>' + esc(f.k) + '</dt><dd>' + esc(f.v) + '</dd></div>';
    }).join('') + '</dl></aside>';
  }
  function lead(it) {
    return '<article class="lead"><p class="kicker">' + esc(it.kicker) + '</p>' +
      headline(it, 'h3') + photo(it, '3 / 2', true) +
      '<p class="txt">' + esc(it.summary) + '</p>' + facts(it) + why(it) + more(it.more) + '</article>';
  }
  function top(it) {
    return '<article class="item"><p class="kicker">' + esc(it.kicker) + '</p>' +
      headline(it, 'h3') + photo(it, '2 / 1', true) +
      '<p class="txt">' + esc(it.summary) + '</p>' + why(it) + more(it.more) + '</article>';
  }
  function track(t, date) {
    var n = daysBetween(t.since, date) + 1;
    var td = t.today || {};
    var tl = (t.timeline || []).slice(-5);
    return '<article class="trk">' +
      '<p class="kicker">' + esc(t.kicker) + (t.status ? '<span class="st">' + esc(t.status) + '</span>' : '') + '</p>' +
      '<div class="trk-h"><h3>' + esc(t.title) + '</h3>' +
      '<div class="day"><b>' + n + '</b><span>일째</span><i>' + esc(t.sinceLabel || fmtMD(t.since) + ' 시작') + '</i></div></div>' +
      photo(td, '3 / 2') +
      '<p class="today"><b>오늘</b>' + esc(td.summary) + '</p>' +
      '<ol class="tl">' + tl.map(function (e, i) {
        return '<li' + (i === tl.length - 1 ? ' class="now"' : '') + '><span class="d">' + esc(fmtMD(e.date)) + '</span>' +
          '<a href="' + esc(e.url) + '" target="_blank" rel="noopener noreferrer">' + esc(e.text) + '<span class="s">' + esc(e.source) + ' ↗</span></a></li>';
      }).join('') + '</ol></article>';
  }
  function brief(it) {
    return '<article class="brf">' + photo(it, '4 / 3') +
      '<div><p class="kicker">' + esc(it.kicker) + '</p>' + headline(it, 'h4') +
      '<p class="txt">' + esc(it.summary) + '</p></div></article>';
  }

  /* ── 통계 ─────────────────────────────────────────── */
  function items(ed) {
    var out = [];
    if (ed.front && ed.front.lead) out.push(ed.front.lead);
    ((ed.front && ed.front.tops) || []).forEach(function (x) { out.push(x); });
    (ed.briefs || []).forEach(function (x) { out.push(x); });
    return out;
  }
  function readMinutes(ed) {
    var n = 0;
    items(ed).forEach(function (it) {
      n += len(it.headline) + len(it.summary) + len(it.why);
      (it.facts || []).forEach(function (f) { n += len(f.k) + len(f.v); });
    });
    (ed.tracking || []).forEach(function (t) {
      n += len(t.title) + len(t.today && t.today.summary);
      (t.timeline || []).slice(-5).forEach(function (e) { n += len(e.text); });
    });
    return Math.max(1, Math.round(n / CHARS_PER_MIN));
  }
  function collect(ed) {
    var urls = {}, srcs = [];
    function add(u, s) { if (u) urls[u] = 1; if (s && srcs.indexOf(s) < 0) srcs.push(s); }
    items(ed).forEach(function (it) { add(it.url, it.source); (it.more || []).forEach(function (m) { add(m.url, m.source); }); });
    (ed.tracking || []).forEach(function (t) {
      if (t.today) add(t.today.url, t.today.source);
      (t.timeline || []).forEach(function (e) { add(e.url, e.source); });
    });
    return { links: Object.keys(urls).length, sources: srcs };
  }

  /* ── 페이지 ───────────────────────────────────────── */
  function render(date) {
    var ed = D.editions[date];
    var man = D.manifest || [date];
    var idx = man.indexOf(date);
    var prev = idx > 0 ? man[idx - 1] : null;
    var next = idx >= 0 && idx < man.length - 1 ? man[idx + 1] : null;
    var info = collect(ed);
    var mins = readMinutes(ed);
    var tops = (ed.front && ed.front.tops) || [];

    function nav(cls) {
      return '<nav class="' + cls + '" aria-label="호 이동">' +
        '<a class="' + (prev ? '' : 'off') + '" href="#' + (prev || date) + '" rel="prev">← 이전 호</a>' +
        '<a class="' + (next ? '' : 'off') + '" href="#' + (next || date) + '" rel="next">다음 호 →</a>' +
        (cls === 'eds' ? '<button type="button" onclick="window.print()">인쇄</button>' : '') + '</nav>';
    }
    var html =
      '<header class="mast">' +
      '<div class="mast-top"><span>제 <b>' + (idx >= 0 ? idx + 1 : 1) + '</b> 호</span><span class="c">' + esc(SITE.en) + '</span><span><b>' + esc(fmtDot(date)) + '</b> ' + WD[toDate(date).getDay()] + '</span></div>' +
      '<h1 class="nameplate"><a href="#' + (man[man.length - 1] || date) + '">' + esc(SITE.name) + '</a></h1>' +
      '<div class="rule2"></div>' +
      '<div class="mast-sub"><div class="stats"><span>' + esc(fmtLong(date)) + '</span><span>읽는 시간 약 <b>' + mins + '분</b></span><span>원문 링크 ' + info.links + '개</span></div>' + nav('eds') + '</div>' +
      '</header>' +
      '<main>' +
      '<section class="front" aria-label="1면">' + (ed.front && ed.front.lead ? lead(ed.front.lead) : '') +
      '<div class="tops">' + tops.map(top).join('') + '</div></section>' +
      ((ed.tracking && ed.tracking.length) ?
        '<section class="sec" aria-label="추적 이슈"><div class="sec-h"><h2><i>Tracking</i>추적 이슈</h2><p>며칠째 이어지는 이슈의 오늘 변화</p></div>' +
        '<div class="track-grid">' + ed.tracking.map(function (t) { return track(t, date); }).join('') + '</div></section>' : '') +
      ((ed.briefs && ed.briefs.length) ?
        '<section class="sec" aria-label="단신"><div class="sec-h"><h2><i>Briefs</i>단신</h2><p>그 밖에 알아둘 소식</p></div>' +
        '<div class="brf-grid">' + ed.briefs.map(brief).join('') + '</div></section>' : '') +
      '</main>' +
      '<footer class="foot">' +
      '<p class="src"><b>출처</b>' + esc(info.sources.join(' · ')) + '</p>' +
      '<p class="fine">' + (ed.generatedAt ? esc(fmtDot(ed.generatedAt.slice(0, 10))) + ' ' + esc(ed.generatedAt.slice(11, 16)) + ' KST 발행 · ' : '') +
      '요약·편집 Claude · 각 기사의 제목과 링크는 해당 매체가 공개한 것이며, 사진의 저작권은 각 매체에 있습니다. 사진이나 제목을 누르면 원문 기사로 이동합니다. 요약에 오류가 있을 수 있으니 중요한 내용은 원문으로 확인하세요.</p>' +
      nav('navs') + '</footer>';

    document.title = SITE.name + ' · ' + fmtDot(date) + ' (제' + (idx >= 0 ? idx + 1 : 1) + '호)';
    app.innerHTML = html;
    [].forEach.call(app.querySelectorAll('.ht img'), function (im) {
      var box = im.parentNode;
      if (im.complete) box.classList.add(im.naturalWidth > 0 ? 'ok' : 'noimg');
      else im.addEventListener('load', function () { box.classList.add('ok'); });
    });
    window.scrollTo(0, 0);
  }

  function message(title, body) {
    app.innerHTML = '<div class="empty"><h2>' + esc(title) + '</h2><p>' + esc(body) + '</p></div>';
  }

  function load(date, cb) {
    if (D.editions[date]) return cb(null);
    var s = document.createElement('script');
    s.src = 'data/' + date + '.js?v=' + Date.now();
    s.onload = function () { cb(D.editions[date] ? null : new Error('empty')); };
    s.onerror = function () { cb(new Error('missing')); };
    document.head.appendChild(s);
  }

  function route() {
    var man = D.manifest || [];
    var want = (location.hash || '').replace('#', '');
    var date = /^\d{4}-\d{2}-\d{2}$/.test(want) ? want : man[man.length - 1];
    if (!date) return message('아직 발행된 호가 없습니다', 'data/manifest.js 에 호가 등록되면 이곳에 표시됩니다.');
    load(date, function (err) {
      if (err) return message(date + ' 호를 찾을 수 없습니다', '이전 호·다음 호 버튼으로 이동하거나 가장 최신 호를 열어 보세요.');
      render(date);
    });
  }

  // 이미지가 막히거나 사라진 경우: 글자형 대체 카드로 전환
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (t && t.tagName === 'IMG' && t.parentNode && t.parentNode.classList && t.parentNode.classList.contains('ht')) {
      t.parentNode.classList.add('noimg');
    }
  }, true);

  // ← → 키로 호 이동
  document.addEventListener('keydown', function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    var a = document.querySelector(e.key === 'ArrowLeft' ? 'a[rel=prev]:not(.off)' : e.key === 'ArrowRight' ? 'a[rel=next]:not(.off)' : '#none');
    if (a) location.hash = a.getAttribute('href');
  });

  window.addEventListener('hashchange', route);
  route();
})();
