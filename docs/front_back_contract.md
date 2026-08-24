The JSON structure that the frontend suppose to send to the backend, and the backend suppose to parse it into SQL commands is:
{
    start_date: ...
    end_date: ...
    topic_taxomony: [
        topic1: [...],
        topic2: [...],
        ...
    ]
    event_type: [
        event_type1; [...],
        event_type2; [...],
        ...
    ]
    categories: [
        category1,
        category2,
        ...
    ]
    categories_audience: [
        categories_audience1,
        categories_audience2,
        ...
    ]
}