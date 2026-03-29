const state={games:[],review:null,idx:0,flipped:false,autoplay:null};
const pieces={p:'♟',r:'♜',n:'♞',b:'♝',q:'♛',k:'♚',P:'♙',R:'♖',N:'♘',B:'♗',Q:'♕',K:'♔'};
const labelColors={Book:'#9aa3ad',Brilliant:'#7c4dff',Great:'#2e7d32',Best:'#1b5e20',Excellent:'#2e7d32',Good:'#43a047',Inaccuracy:'#f9a825',Mistake:'#ef6c00',Miss:'#fb8c00',Blunder:'#c62828'};

const $=id=>document.getElementById(id);
const EMPTY_TEXT={
 noReview:'No review loaded. Select a game to begin.',
 backendError:'Backend error while loading review.',
 heuristicNoMoves:'Heuristic fallback loaded, but move-by-move review data is unavailable for interactive playback.',
};

function setStatus(msg){$('status').textContent=msg;}
function getMoves(review){return Array.isArray(review?.reviewed_moves)?review.reviewed_moves:[];}
function hasMoves(review){return getMoves(review).length>0;}

async function loadGames(){
 const u=$('username').value.trim(); const d=$('days').value||3; if(!u)return;
 setStatus('Loading games...');
 const r=await fetch(`/api/games?username=${encodeURIComponent(u)}&days=${d}`); const data=await r.json();
 state.games=data.games||[]; $('games').innerHTML='';
 state.games.forEach(g=>{const el=document.createElement('div');el.className='gameItem';el.textContent=`${g.white} vs ${g.black} • ${g.time_class} • ${g.end}`;el.onclick=()=>loadReview(u,d,g.url);$('games').appendChild(el);});
 setStatus(`Loaded ${state.games.length} games`);
}

async function loadReview(username,days,url){
 setStatus('Analyzing selected game...');
 const r=await fetch(`/api/review?username=${encodeURIComponent(username)}&days=${days}&game_url=${encodeURIComponent(url)}`); const data=await r.json();
 if(data?.error){
  state.review={error:data.error,reviewed_moves:[]}; state.idx=0; renderAll(); setStatus(`${EMPTY_TEXT.backendError} ${data.error}`); return;
 }
 state.review=data; state.idx=0; renderAll();
 if(!hasMoves(data)){setStatus(EMPTY_TEXT.heuristicNoMoves);return;}
 setStatus('Review ready');
}

function fenToBoard(fen){const rows=fen.split(' ')[0].split('/');const out=[];rows.forEach(r=>{for(const c of r){if(+c)for(let i=0;i<+c;i++)out.push('');else out.push(c);}});return out;}
function sqToXY(sq){const file=sq.charCodeAt(0)-97, rank=8-parseInt(sq[1]);return [file,rank];}
function uciToSquares(uci){return [uci.slice(0,2),uci.slice(2,4)];}

function renderBoard(){const review=state.review;const boardEl=$('board');const arrowEl=$('arrowLayer');
 if(!review){boardEl.innerHTML='<div class="boardEmpty">No review loaded</div>';arrowEl.innerHTML='';return;}
 const moves=getMoves(review); const mv=moves[state.idx];const fen=mv?mv.fen_after:moves[0]?.fen_before;
 if(review.error){boardEl.innerHTML='<div class="boardEmpty boardError">Backend error. Unable to load interactive board.</div>';arrowEl.innerHTML='';return;}
 if(!fen){boardEl.innerHTML='<div class="boardEmpty">Heuristic fallback: no move-by-move board data available.</div>';arrowEl.innerHTML='';return;}
 const b=fenToBoard(fen); const order=[0,1,2,3,4,5,6,7]; if(state.flipped)order.reverse();
 boardEl.innerHTML='';
 for(const r of order){for(const f of order){const i=r*8+f;const sq=document.createElement('div');sq.className='sq '+(((r+f)%2)?'dark':'light');
 const p=b[i];sq.textContent=p?pieces[p]:''; sq.dataset.file=f; sq.dataset.rank=r; boardEl.appendChild(sq);} }
 if(mv && $('highlightToggle').checked){const [pf,pt]=uciToSquares(mv.uci); highlightSquare(pf,'highlight'); highlightSquare(pt,'highlight');
 const [bf,bt]=uciToSquares(mv.best_move_uci||mv.uci); highlightSquare(bf,'best'); highlightSquare(bt,'best');}
 renderArrow();
}
function highlightSquare(name,klass){const [f,r]=sqToXY(name); const files=state.flipped?[7-f]:[f]; const ranks=state.flipped?[7-r]:[r];
 const idx=ranks[0]*8+files[0]; const el=$('board').children[idx]; if(el)el.classList.add(klass);}

function renderArrow(){const svg=$('arrowLayer'); svg.innerHTML=''; if(!$('arrowToggle').checked||!state.review)return; const moves=getMoves(state.review); const mv=moves[state.idx]; if(!mv||!mv.best_move_uci)return;
 const [a,b]=uciToSquares(mv.best_move_uci); const [fx,fy]=sqToXY(a); const [tx,ty]=sqToXY(b); const map=v=>state.flipped?7-v:v;
 const size=svg.clientWidth/8; const x1=(map(fx)+0.5)*size,y1=(map(fy)+0.5)*size,x2=(map(tx)+0.5)*size,y2=(map(ty)+0.5)*size;
 const ns='http://www.w3.org/2000/svg';
 const defs=document.createElementNS(ns,'defs');
 const marker=document.createElementNS(ns,'marker');marker.setAttribute('id','arr');marker.setAttribute('markerWidth','8');marker.setAttribute('markerHeight','8');marker.setAttribute('refX','6');marker.setAttribute('refY','3');marker.setAttribute('orient','auto');
 const tip=document.createElementNS(ns,'path');tip.setAttribute('d','M0,0 L0,6 L6,3 z');tip.setAttribute('fill','#4ca3ff');marker.appendChild(tip);defs.appendChild(marker);svg.appendChild(defs);
 const line=document.createElementNS(ns,'line');line.setAttribute('x1',x1);line.setAttribute('y1',y1);line.setAttribute('x2',x2);line.setAttribute('y2',y2);line.setAttribute('stroke','#4ca3ff');line.setAttribute('stroke-width','6');line.setAttribute('opacity','0.75');line.setAttribute('marker-end','url(#arr)');svg.appendChild(line);
}

function renderInfo(){const r=state.review;const badge=$('labelBadge');
 if(!r){
  badge.textContent='—';badge.style.background='#607d8b';$('shortExpl').textContent=EMPTY_TEXT.noReview;$('detailExpl').textContent='Load a game to view move-by-move coaching details.';$('moveMeta').textContent='No review loaded';$('reviewFacts').innerHTML='';$('summary').innerHTML='';return;
 }
 if(r.error){
  badge.textContent='Error';badge.style.background='#c62828';$('shortExpl').textContent=EMPTY_TEXT.backendError;$('detailExpl').textContent=String(r.error);$('moveMeta').textContent='Backend error';$('reviewFacts').innerHTML='';$('summary').innerHTML='';return;
 }
 const moves=getMoves(r);const mv=moves[state.idx];
 if(!mv){
  badge.textContent='—';badge.style.background='#607d8b';$('shortExpl').textContent=EMPTY_TEXT.heuristicNoMoves;$('detailExpl').textContent='This game was analyzed without engine move timeline data, so interactive board stepping is unavailable.';$('moveMeta').textContent='Heuristic fallback with no move-by-move data';$('reviewFacts').innerHTML='';$('summary').innerHTML='';return;
 }
 badge.textContent=mv.label;badge.style.background=labelColors[mv.label]||'#607d8b';badge.classList.remove('pop');void badge.offsetWidth;badge.classList.add('pop');
 $('shortExpl').textContent=mv.short_explanation; $('detailExpl').textContent=mv.detailed_explanation;
 $('moveMeta').textContent=`Move ${mv.move_number_display} ${mv.san} • Played: ${mv.san} • Best: ${mv.best_move_san}`;
 $('reviewFacts').innerHTML=`<div><b>EP Loss:</b> ${mv.expected_points_loss}</div><div><b>Tactical tags:</b> ${(mv.tactical_tags||[]).join(', ')||'none'}</div>`;
 const counts=Object.entries(r.move_quality_counts||{}).map(([k,v])=>`<li>${k}: ${v}</li>`).join('');
 const key=(r.key_moments||[]).map(k=>`<li>${k.move_number_display} ${k.san} (${k.label})</li>`).join('');
 const miss=(r.best_missed_opportunities||[]).map(k=>`<li>${k.move_number_display} ${k.san} → ${k.best_move_san}</li>`).join('');
 const themes=Object.entries(r.tactical_themes||{}).map(([k,v])=>`<li>${k}: ${v}</li>`).join('');
 $('summary').innerHTML=`<h4>Label counts</h4><ul>${counts}</ul><h4>Key moments</h4><ul>${key}</ul><h4>Top mistakes</h4><ul>${miss}</ul><h4>Tactical themes</h4><ul>${themes}</ul>`;
}

function renderMoveList(){const r=state.review;if(!r)return; $('moveList').innerHTML='';
 const moves=getMoves(r); if(!moves.length){$('moveList').textContent=r.error?'No moves available due to backend error.':'No interactive moves available for this review.';return;}
 moves.forEach((m,i)=>{const e=document.createElement('span');e.className='mv'+(i===state.idx?' active':'');e.textContent=`${m.move_number_display} ${m.san}`;e.onclick=()=>{state.idx=i;renderAll();};$('moveList').appendChild(e);});
}
function renderAll(){renderBoard();renderInfo();renderMoveList();}
function next(){if(!state.review)return; const moves=getMoves(state.review); if(!moves.length)return; state.idx=Math.min(moves.length-1,state.idx+1);renderAll();}
function prev(){if(!state.review)return; const moves=getMoves(state.review); if(!moves.length)return; state.idx=Math.max(0,state.idx-1);renderAll();}

$('loadGames').onclick=loadGames; $('nextBtn').onclick=next; $('prevBtn').onclick=prev;
$('flipBtn').onclick=()=>{state.flipped=!state.flipped;renderBoard();};
$('arrowToggle').onchange=renderBoard; $('highlightToggle').onchange=renderBoard;
$('autoplayBtn').onclick=()=>{if(state.autoplay){clearInterval(state.autoplay);state.autoplay=null;return;} state.autoplay=setInterval(()=>{if(!state.review)return; const moves=getMoves(state.review); if(!moves.length||state.idx>=moves.length-1){clearInterval(state.autoplay);state.autoplay=null;return;} next();},900);};
window.addEventListener('keydown',e=>{if(e.key==='ArrowRight')next(); if(e.key==='ArrowLeft')prev();});
