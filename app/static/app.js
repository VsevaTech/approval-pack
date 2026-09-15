// Progressive enhancement. Every page works without JavaScript: the decision
// form is a plain HTML POST and the review link is selectable text. This file
// only removes two small frictions.

// 1. Copy the review link to the clipboard.
document.addEventListener("click", function (event) {
  var trigger = event.target.closest("[data-copy]");
  if (!trigger) return;
  var field = document.getElementById(trigger.getAttribute("data-copy"));
  if (!field) return;
  field.select();
  var done = function () {
    var label = trigger.textContent;
    trigger.textContent = "Copied";
    setTimeout(function () { trigger.textContent = label; }, 1500);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(field.value).then(done, done);
  } else {
    document.execCommand("copy");
    done();
  }
});

// 2. Submit the decision without a full page reload and swap in the fragment
//    the server returns. The request carries `HX-Request: true`, the same
//    convention htmx uses, so the server needs no special case for this file
//    and htmx could replace it unchanged.
document.addEventListener("submit", function (event) {
  var form = event.target.closest("form[data-swap-target]");
  if (!form) return;
  var target = document.querySelector(form.getAttribute("data-swap-target"));
  if (!target || !window.fetch || !window.FormData) return;

  event.preventDefault();
  var body = new FormData(form);
  var submitter = event.submitter;
  if (submitter && submitter.name) body.append(submitter.name, submitter.value);

  fetch(form.action, {
    method: "POST",
    body: body,
    headers: { "HX-Request": "true" },
    credentials: "same-origin"
  })
    .then(function (response) { return response.text(); })
    .then(function (html) { target.innerHTML = html; })
    .catch(function () { form.submit(); });
});
