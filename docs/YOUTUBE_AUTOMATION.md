# YouTube Shorts setup, research and posting

## 1. Connect your channel

1. In Google Cloud, enable **YouTube Data API v3** for the project. Configure **Google Auth Platform** and create an OAuth client of type **Web application**. Add your Google account as a test user if the app is external and still in Testing.
2. In MJ-Cliping, open **Settings → Connected apps → YouTube → Set up**. Copy the callback URL it displays into the client's authorized redirect URIs. Use the same host, port, and path, including the difference between `localhost` and `127.0.0.1`.
3. Enter that client's ID and secret in the YouTube setup panel, then choose **Continue with Google**. Select the Google account that owns or manages the intended YouTube channel and grant the requested read and upload scopes.
4. Check the connected channel name. Start with the **Private** visibility setting for one authorized clip, then check the resulting upload in YouTube Studio.

An OAuth token can expire or be revoked. If a queued post reports an authorization problem, reconnect the channel and retry that queue entry. If Google shows **Error 403: access_denied** on its consent screen, check the OAuth app's Audience and test-user list. See [Google's web server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server) and [token expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

## 2. Research clip metadata

Save and test an active LLM in **Settings → AI**. YouTube search uses a connected account or the optional `PEAKCUT_YOUTUBE_RESEARCH_KEY` in `.env`. Restrict a research key to YouTube Data API v3 and store it locally. A research key supplies search results. Uploads use the connected channel's OAuth grant.

Open a rendered clip, choose a search region, and click **Research and generate 10 options**. MJ-Cliping asks the model for a topic phrase and uses it to find recent gaming videos from the past 30 days. Review its displayed source links. The LLM uses the results to inform keywords and uses the clip captions and context to write each title, description and set of relevant hashtags.

Each complete AI description has at least 1,500 characters. Apply all the post text or use a candidate's title alone and keep editing. If YouTube search is unavailable, check the search status shown in the editor. The LLM can draft from the clip alone when search returns no references. Verify names, scores, quotes and claims before posting.

## 3. Post one clip or schedule a batch

- **Single clip:** Open the clip and select its YouTube destination and visibility. Choose **Post to YouTube** to start the upload through the app's queue.
- **Batch:** Select up to 200 finished clips, choose the YouTube destination and visibility, and schedule the selection. The worker starts the first eligible clip when due and spaces successful uploads at least 10 minutes apart within the batch.
- **Visibility:** Private is the initial choice. Choose **Unlisted** or **Public** explicitly for the intended audience. Google can apply additional restrictions to uploads from an unverified API project. See [the upload API documentation](https://developers.google.com/youtube/v3/docs/videos/insert).

Review channel, clip, title, captions, audio, and visibility before queuing. Use footage and music you own or have permission to republish. For a tournament, see the [review checklist](TOURNAMENT_WORKFLOW.md).

The Shorts uploader accepts finished 9:16 clips up to three minutes long. Trim or re-render an older clip before retrying if the queue reports a format mismatch.

## 4. Review the queue and limits

Keep MJ-Cliping running, the computer awake, and its network connection available when uploads are due. Check the queue for scheduled, uploading, posted, and failed entries. Open the returned video link after a successful upload. If a post fails, read the queue error, correct the cause, and retry the existing entry. Where an upload might already have reached YouTube, check the destination channel before scheduling the same clip again.

A 200-clip batch can extend over multiple days. A single queue using a 10-minute interval has a theoretical maximum of 144 slots per 24 hours, before upload time, delays, and quota. Google currently lists separate default project limits of 100 `videos.insert` calls and 100 `search.list` calls per day. The limits reset at midnight Pacific Time. Channel-specific upload limits and local settings can reduce throughput further. For more API capacity, review your quota in Google Cloud and follow Google's extension process. See [quota costs and limits](https://developers.google.com/youtube/v3/determine_quota_cost) and [quota and compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits).

## 5. Add music

Use an instrumental file you own or are licensed to use, set its volume, and listen to the rendered clip before posting. When you want a song from YouTube's licensed Shorts catalog, add it in YouTube's own creation tools. See [YouTube's Shorts audio guidance](https://support.google.com/youtube/answer/16215842).
