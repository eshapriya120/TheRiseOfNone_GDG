// This script must run on the correct trigger:
//   Event source = From form
//   Event type = On form submit
// Do not use "On open".

function onFormSubmit(e) {
  const response = e.response;
  const itemResponses = response.getItemResponses();

  const values = {};
  itemResponses.forEach(function(itemResponse) {
    const title = itemResponse.getItem().getTitle();
    const answer = itemResponse.getResponse();

    if (Array.isArray(answer)) {
      values[title] = answer.join(', ');
    } else {
      values[title] = answer;
    }
  });

  const payload = {
    student_username: values['Student Username'] || values['Username'] || values['Email'] || '',
    drive_name: values['Drive Name'] || values['Drive'] || 'Tech Drive 2026',
    attendance: values['Did you attend the previous drive?'] || values['Attendance'] || 'unknown',
    feedback_submitted: values['Did you submit feedback?'] || values['Feedback Submitted'] || 'unknown',
    placement_status: values['Placement Status'] || values['Placed'] || 'not_placed',
    permission_reason: values['Permission Reason'] || ''
  };

  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  // Replace this with your public Flask app URL or ngrok URL.
  const url = 'http://127.0.0.1:5000';
  UrlFetchApp.fetch(url, options);
}
