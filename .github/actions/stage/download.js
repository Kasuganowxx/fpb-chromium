import { DefaultArtifactClient } from '@actions/artifact';

// Runs in a separate process so file handles leaked by failed download retries
// in @actions/artifact are released before the downloaded archive is extracted.
// Optional third argument: run id of another run in this repo (needs env GITHUB_TOKEN with actions: read).
async function run() {
    const [artifactName, path, runId] = process.argv.slice(2);
    const artifact = new DefaultArtifactClient();
    let options = {};
    if (runId) {
        const [repositoryOwner, repositoryName] = process.env.GITHUB_REPOSITORY.split('/');
        options = {findBy: {token: process.env.GITHUB_TOKEN, workflowRunId: Number(runId), repositoryOwner, repositoryName}};
    }
    const artifactInfo = await artifact.getArtifact(artifactName, options);
    await artifact.downloadArtifact(artifactInfo.artifact.id, {path, ...options});
}

run().catch(err => {
    console.error(err);
    process.exit(1);
});
