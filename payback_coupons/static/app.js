document.addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-toggle-target]');
  if (toggle) {
    const target = document.getElementById(toggle.getAttribute('data-toggle-target'));
    if (target) target.classList.toggle('collapsed');
  }
  const form = event.target.closest('form[data-confirm]');
  if (form && event.target.matches('button, input[type="submit"]')) {
    const message = form.getAttribute('data-confirm') || 'Wirklich ausführen?';
    if (!confirm(message)) event.preventDefault();
  }
});
document.addEventListener('change', (event) => {
  const input = event.target;
  if (!input.matches('input[type="file"]')) return;
  const form = input.closest('form');
  const preview = form ? form.querySelector('[data-preview]') : null;
  if (!preview) return;
  preview.innerHTML = '';
  const file = input.files && input.files[0];
  if (!file || !file.type.startsWith('image/')) return;
  const img = document.createElement('img');
  img.alt = 'Vorschau';
  img.src = URL.createObjectURL(file);
  preview.appendChild(img);
});