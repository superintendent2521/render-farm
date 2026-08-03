const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';

document.querySelectorAll('[data-dialog]').forEach(button => {
  button.addEventListener('click', () => document.getElementById(button.dataset.dialog).showModal());
});
document.querySelectorAll('.dialog-close').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));

const fileInput = document.getElementById('project-file');
if (fileInput) fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  if (!file) return;
  const status = document.getElementById('upload-status');
  const submit = document.getElementById('submit-job');
  submit.disabled = true;
  try {
    status.textContent = 'Preparing upload…';
    const init = await fetch('/api/v1/uploads', {method:'POST', headers:{'content-type':'application/json','x-csrf-token':csrf}, body:JSON.stringify({filename:file.name,total_size:file.size})});
    if (!init.ok) throw new Error(await init.text());
    const session = await init.json();
    const completed = [];
    for (let offset=0, part=1; offset<file.size; offset += session.chunk_size, part++) {
      const blob = file.slice(offset, Math.min(offset + session.chunk_size, file.size));
      status.textContent = `Uploading ${Math.round(offset/file.size*100)}%…`;
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
      const target = session.backend === 's3' ? session.parts[part-1].url : `/api/v1/uploads/${session.id}/parts/${part}`;
      const headers = session.backend === 's3' ? {} : {'x-csrf-token':csrf,'x-chunk-sha256':hash};
      const sent = await fetch(target, {method:'PUT', headers, body:blob});
      if (!sent.ok) throw new Error(await sent.text());
      if (session.backend === 's3') completed.push({part_number:part,etag:sent.headers.get('etag')});
    }
    status.textContent = 'Validating project…';
    const done = await fetch(`/api/v1/uploads/${session.id}/complete`, {method:'POST',headers:{'content-type':'application/json','x-csrf-token':csrf},body:JSON.stringify({parts:completed})});
    if (!done.ok) throw new Error(await done.text());
    const result = await done.json();
    document.getElementById('upload-id').value = result.id;
    status.textContent = `Ready · ${result.blend_path}`;
    status.className = 'alert good';
    submit.disabled = false;
  } catch (error) {
    status.textContent = `Upload failed: ${error.message}`;
    status.className = 'alert bad';
  }
});

