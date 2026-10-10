(function () {
  'use strict';
  const form = document.querySelector('[data-feedback-form]');
  if (!form) return;
  const kind = form.querySelector('[data-feedback-kind]');
  const fields = form.querySelector('[data-bug-fields]');
  function updateFields() {
    const isBug = kind.value === 'bug';
    fields.hidden = !isBug;
    fields.querySelectorAll('textarea').forEach(function (field) {
      field.required = isBug;
    });
  }
  kind.addEventListener('change', updateFields);
  updateFields();
})();
