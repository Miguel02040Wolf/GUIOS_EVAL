// GUIOS EVAL: guardado automático de los pasos 2 y 3
function postJSON(url, data){
  return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
    .then(function(r){return r.json();});
}
function avisoGuardado(){
  var s=document.getElementById('saved'); if(!s) return;
  s.classList.add('show'); clearTimeout(window._sv); window._sv=setTimeout(function(){s.classList.remove('show');},1400);
}
var NIV={1:'Irrelevante',2:'Opcional',3:'Importante',4:'Fundamental'};

function initPaso2(eid){
  document.querySelectorAll('#tabla-factores tr[data-key]').forEach(function(tr){
    var key=tr.dataset.key, nombre=tr.dataset.nombre;
    function enviar(datos){
      datos.factor_key=key; datos.nombre=nombre;
      postJSON('/api/evaluaciones/'+eid+'/voto',datos).then(function(r){
        if(!r.ok){alert(r.error);return;}
        tr.querySelector('.c-id').innerHTML=(r.id?NIV[r.id]:'<span class="muted">sin valorar</span>')+(r.votos>1?' <span class="small muted">('+r.votos+' votos)</span>':'')+(r.desacuerdo?' <span class="chip warn">desacuerdo</span>':'');
        tr.querySelector('.c-ir').innerHTML=r.ir?'<span class="chip '+(r.relevante?'info':'')+'">'+r.ir_txt+'</span>':'-';
        tr.classList.toggle('off',!r.relevante);
        document.getElementById('m-rel').textContent=r.relevantes;
        document.getElementById('m-sin').textContent=r.sin_id;
        avisoGuardado();
      });
    }
    tr.querySelectorAll('.seg.imp button').forEach(function(b){
      b.addEventListener('click',function(){
        tr.querySelectorAll('.seg.imp button').forEach(function(x){x.classList.remove('sel');});
        b.classList.add('sel');
        var d={id_valor:parseInt(b.dataset.v)}; var a=tr.querySelector('select.alc'); if(a) d.alcance=a.value;
        enviar(d);
      });
    });
    var a=tr.querySelector('select.alc');
    if(a) a.addEventListener('change',function(){enviar({alcance:a.value});});
  });
}

function initPaso3(eid,total,hechas){
  var cont=hechas;
  function progreso(box){
    cont++;
    document.getElementById('prog-txt').textContent=cont+'/'+total+' subfactores';
    document.getElementById('prog-bar').style.width=(100*cont/total)+'%';
    var fl=document.querySelector('.flist a.on'); if(fl){var c=fl.querySelector('.cnt'); var n=parseInt(c.textContent)+1; c.textContent=n;
      var tot=box.parentNode.querySelectorAll('.sub[data-key]').length; fl.querySelector('.bar i').style.width=(100*n/tot)+'%';}
  }
  document.querySelectorAll('.sub[data-key]').forEach(function(box){
    var key=box.dataset.key, texto=box.dataset.texto;
    function enviar(d){
      d.sub_key=key; d.texto=texto;
      return postJSON('/api/evaluaciones/'+eid+'/respuesta',d).then(function(r){
        if(!r.ok){alert(r.error);return;}
        document.getElementById('pm').textContent=r.pm_txt;
        var f=document.getElementById('foda'); f.className='chip '+(r.foda||''); f.textContent=r.foda||'sin evaluar';
        box.querySelector('.c-ps').textContent=r.ps_txt;
        var cn=box.querySelector('.c-n'); if(cn) cn.textContent=r.n+(r.n===1?' respuesta':' respuestas');
        avisoGuardado();
      });
    }
    // marcar un valor (clic, acción rápida o sugerencia de IA aceptada)
    box._marcar=function(v,extra){
      var nuevo=!box.querySelector('.seg.ps button.sel');
      box.querySelectorAll('.seg.ps button').forEach(function(x){x.classList.toggle('sel',parseInt(x.dataset.v)===v);});
      box.classList.add('hecho');
      var d={valor:v}; if(extra){for(var k in extra){d[k]=extra[k];}}
      if(extra&&extra.comentario!==undefined){var c=box.querySelector('.com'); if(c)c.value=extra.comentario;}
      if(extra&&extra.evidencia!==undefined){var e=box.querySelector('.evi'); if(e)e.value=extra.evidencia;}
      var chip=box.querySelector('.chip.ia');
      if(extra&&extra.origen){if(!chip){chip=document.createElement('span');chip.className='chip ia';box.querySelector('.txt').appendChild(chip);} chip.textContent='IA · '+extra.origen.slice(3);}
      else if(chip){chip.remove();}
      return enviar(d).then(function(){if(nuevo)progreso(box);});
    };
    box.querySelectorAll('.seg.ps button').forEach(function(b){
      b.addEventListener('click',function(){box._marcar(parseInt(b.dataset.v));});
    });
    var com=box.querySelector('.com'), evi=box.querySelector('.evi');
    if(com) com.addEventListener('change',function(){enviar({comentario:com.value});});
    if(evi) evi.addEventListener('change',function(){enviar({evidencia:evi.value});});
  });

  // acciones rápidas
  var qa=document.getElementById('qa-aplicar');
  if(qa) qa.addEventListener('click',function(){
    var v=parseInt(document.getElementById('qa-valor').value), solo=document.getElementById('qa-pend').checked;
    var cajas=[].slice.call(document.querySelectorAll('.sub[data-key]')).filter(function(b){return !solo||!b.querySelector('.seg.ps button.sel');});
    if(!cajas.length){alert('No hay subfactores pendientes en este factor.');return;}
    if(!confirm('Se marcarán '+cajas.length+' subfactores. ¿Continuar?'))return;
    cajas.reduce(function(p,b){return p.then(function(){return b._marcar(v);});},Promise.resolve());
  });

  // asistente de IA
  var bIA=document.getElementById('ia-sugerir');
  if(bIA) bIA.addEventListener('click',function(){
    var est=document.getElementById('ia-estado');
    bIA.disabled=true; est.textContent='Consultando la IA... (de 5 a 30 segundos)';
    document.querySelectorAll('.ia-box').forEach(function(x){x.remove();});
    postJSON('/api/evaluaciones/'+eid+'/ia/subfactores',{factor_key:bIA.dataset.factor}).then(function(r){
      bIA.disabled=false;
      if(!r.ok){est.textContent=r.error||'La IA no respondió.';return;}
      est.innerHTML='Sugerencias de <b>'+r.proveedor+'</b> ('+r.modelo+'). Acepta o descarta cada una; nada se guarda hasta que la aceptes.';
      document.getElementById('ia-todas').hidden=false;
      var nombres=['','No cumple','Desconozco','Cumple parcialmente','Cumple'];
      r.propuestas.forEach(function(p){
        var box=document.querySelector('.sub[data-key="'+p.key+'"]'); if(!box)return;
        var d=document.createElement('div'); d.className='ia-box'; d.dataset.conf=p.confianza;
        var fuentes=p.fuentes.map(function(f){return '<a href="'+f+'" target="_blank" rel="noopener">'+f.replace('https://doi.org/','')+'</a>';}).join(', ');
        d.innerHTML='<b>Sugerencia IA:</b> '+nombres[p.valor]+' <span class="chip ia">'+p.confianza+'% confianza</span><div>'+
          p.justificacion.replace(/</g,'&lt;')+'</div>'+(fuentes?'<div class="small">Fuentes: '+fuentes+'</div>':'')+
          '<div class="acciones"><button type="button" class="btn sm ok">Aceptar</button><button type="button" class="btn sm">Descartar</button></div>';
        d._aceptar=function(){d.remove(); return box._marcar(p.valor,{origen:'ia:'+r.proveedor,comentario:'[IA '+r.proveedor+', '+p.confianza+'%] '+p.justificacion,evidencia:p.fuentes.join(' ')});};
        d.querySelector('.ok').addEventListener('click',d._aceptar);
        d.querySelectorAll('button')[1].addEventListener('click',function(){d.remove();});
        box.appendChild(d);
      });
    }).catch(function(){bIA.disabled=false; est.textContent='Error de conexión con el servidor.';});
  });
  var bT=document.getElementById('ia-todas');
  if(bT) bT.addEventListener('click',function(){
    var cajas=[].slice.call(document.querySelectorAll('.ia-box')).filter(function(x){return parseInt(x.dataset.conf)>=70;});
    if(!cajas.length){alert('No hay sugerencias con confianza de 70 % o más.');return;}
    cajas.reduce(function(p,x){return p.then(function(){return x._aceptar();});},Promise.resolve());
  });
}

function abrirFactor(f){
  var d=document.getElementById('dlg-factor');
  document.getElementById('dlg-titulo').textContent=f?'Editar factor':'Nuevo factor';
  document.getElementById('ff-id').value=f?f.id:'';
  document.getElementById('ff-nombre').value=f?f.nombre:'';
  document.getElementById('ff-dim').value=f?f.dimension:'Tecnológica';
  document.getElementById('ff-is').value=f?f.is_valor:2;
  document.getElementById('ff-alc').value=f?f.alcance:'Externo';
  document.getElementById('ff-desc').value=f?f.descripcion:'';
  document.getElementById('ff-act').value=f?String(f.activo):'1';
  d.showModal();
}
