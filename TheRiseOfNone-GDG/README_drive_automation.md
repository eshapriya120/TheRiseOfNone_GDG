# Drive automation with Google Forms

## Setup

1. Open your Google Form and go to **Apps Script**.
2. Create a new script and paste the contents of `google_forms_to_webhook.gs`.
3. Replace the placeholder webhook URL in the script with your public Flask app URL.
   - If you are testing locally, use an HTTP tunnel like `ngrok`.
4. Save the script.
5. Go to **Triggers** and add a trigger:
   - Function: `onFormSubmit`
   - Event source: `From form`
   - Event type: `On form submit`

## Important

- Do not use `On open`.
- If the trigger is wrong, the form response will not be sent to your app.
- `127.0.0.1` does not work from Google Apps Script unless you use a tunnel.

## Recommended form question titles

Use these exact titles or adjust the script to match your form:
- Student Username
- Drive Name
- Did you attend the previous drive?
- Did you submit feedback?
- Placement Status
- Permission Reason

## Testing with ngrok

If you are running Flask locally, use `ngrok` to create a public URL:

```bash
ngrok http 5000
```

Then update `google_forms_to_webhook.gs`:

```js
const url = 'https://<your-ngrok-id>.ngrok.app/google-form-webhook';
```

Submit a test form and confirm that the new row appears in `drive_state.csv`.

## Verify the flow

1. Submit a response in the Google Form.
2. Open Apps Script > Executions and confirm the `onFormSubmit` trigger ran.
3. Check `drive_state.csv` for the new student entry.
4. If it did not update, check the Apps Script execution log for errors and verify the public webhook URL.
