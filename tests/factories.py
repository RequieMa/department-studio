from department_studio.domain import LeadCreate


def create_lead(store, directory, handle="atlas", **changes):
    data = dict(
        name="星图 Studio",
        handle=handle,
        role="Build the backend",
        provider="test",
        model_id="model-a",
        workspace=str(directory),
    )
    data.update(changes)
    return store.create_lead(LeadCreate(**data))
