// The home hero's trailer: a poster card that opens the film in a modal dialog, with sound, on request (#216).
(function () {
  const open = document.querySelector('[data-trailer-open]');
  const dialog = document.querySelector('[data-trailer-dialog]');
  if (!open || !dialog || typeof dialog.showModal !== 'function') return;
  const video = dialog.querySelector('[data-trailer-video]');

  // Every way out stops the film; the dialog's own close event is not relied on (some embedded browsers skip it).
  const shut = () => {
    video.pause();
    if (dialog.open) dialog.close();
    open.focus();
  };
  open.addEventListener('click', () => {
    dialog.showModal();
    video.currentTime = 0;
    const playing = video.play();
    if (playing) playing.catch(() => {});   // a refused autoplay leaves the controls to the viewer
  });
  dialog.querySelector('[data-trailer-close]').addEventListener('click', shut);
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); shut(); });   // Escape
  // A click on the backdrop (the dialog element itself, outside the frame) closes it too.
  dialog.addEventListener('click', (event) => { if (event.target === dialog) shut(); });
  dialog.addEventListener('close', () => video.pause());
})();
