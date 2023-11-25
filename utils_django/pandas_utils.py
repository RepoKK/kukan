from typing import List

import pandas as pd


def df_diff(df_left: pd.DataFrame, df_right: pd.DataFrame,
            *, left_name='L', right_name='R', precision=6,
            ignore_column_diff=False, hide_identical_columns=False,
            restricted_to_columns: List[str] = None,
            columns_to_ignore: List[str] = None):
    """
    Return a print-friendly DF with the difference between 2 DF

    The left and right DF needs to have the same columns.
    If the DFs are identical an empty DF is returned.

    The output is a DF with up to 3 rows at the top-level index:

    * Diff:
    Contains the rows with differences.
    They are displayed in pair, left at the top and right at the bottom.
    Top row will have all values, bottom one will have only the values different

    * L-only:
    Contains the rows present only on the left DF

    * R-only:
    Contains the rows present only on the right DF

    :param df_left: Left side DF
    :param df_right: Right side DF
    :param left_name: Name of left side rows
    :param right_name: Name of right side rows
    :param precision: precision float will be rounded to before comparison
    :param ignore_column_diff: ignore the columns which are different
        (present in only one of the DF).
        If False and some columns name are different, KeyError is raised
    :param hide_identical_columns: in the final output, whether to output
        all columns or only the ones with differences
    :param restricted_to_columns: only specified list of columns
        will be considered
    :param columns_to_ignore: specified list of columns will be ignored
        during the diff
    :return: DF containing the differences between left of right


    Example:

    >>> df1 = pd.DataFrame.from_dict({'A': [1, 'cat', 10], 'B': [2, 'bb', 20]})
    >>> df2 = pd.DataFrame.from_dict({'A': [1, 'dog'], 'B': [2, 'bb']})
    >>> df_diff(df1, df2)
                  A   B
    Diff   1 L  cat  bb
             R  dog   "
    L-only 2 L   10  20

    If DF are identical an empty DF is returned

    >>> df_diff(df1, df1)
    Empty DataFrame
    Columns: [A, B]
    Index: []
    """

    assert isinstance(df_left, pd.DataFrame)
    assert isinstance(df_right, pd.DataFrame)

    if restricted_to_columns:
        df_left = df_left.reindex(restricted_to_columns, axis=1)
        df_right = df_right.reindex(restricted_to_columns, axis=1)

    if ignore_column_diff:
        # Drop columns present in only one DF
        common_columns = df_left.columns.intersection(df_right.columns)
        df_left = df_left.reindex(common_columns, axis=1)
        df_right = df_right.reindex(common_columns, axis=1)
    else:
        col_only_in_left = df_left.columns.difference(
            df_right.columns).to_list()
        col_only_in_right = df_right.columns.difference(
            df_left.columns).to_list()
        if col_only_in_left or col_only_in_right:
            raise KeyError(f'Some columns are different. '
                           f'L-only: {col_only_in_left}. '
                           f'R-only: {col_only_in_right}.')

    # Drop columns to ignore
    if columns_to_ignore:
        df_left = df_left.drop(columns=columns_to_ignore, errors='ignore')
        df_right = df_right.drop(columns=columns_to_ignore, errors='ignore')

    # Sort the columns of right to match left
    df_right = df_right[df_left.columns]

    # Left only and right only DF
    left_only_df = df_left.reindex(df_left.index.difference(df_right.index))
    left_only_df = pd.concat([left_only_df], keys=['L'])
    right_only_df = df_right.reindex(df_right.index.difference(df_left.index))
    right_only_df = pd.concat([right_only_df], keys=['R'])

    # Difference for the index in both DF
    index_intersect = df_left.index.intersection(df_right.index)
    df_left = df_left.round(precision).reindex(index_intersect)
    df_right = df_right.round(precision).reindex(index_intersect)

    difference = df_left.ne(df_right) & ~(df_left.isnull() & df_right.isnull())
    line_mask = difference.any(axis=1)
    diff_df = pd.concat([df_left[line_mask],
                         df_right[line_mask][difference].fillna('"')],
                        keys=['L', 'R'])

    # Merge all and format
    final_df = pd.concat([diff_df, left_only_df, right_only_df],
                         keys=['Diff', 'L-only', 'R-only'])
    final_df.index.names = [None] * final_df.index.nlevels

    final_df = (
        final_df.reorder_levels([0, *range(2, final_df.index.nlevels), 1])
        .sort_index()
        .rename(index={'L': left_name, 'R': right_name},
                level=final_df.index.nlevels - 1))

    if hide_identical_columns:
        col_mask = difference.any(axis=0)
        final_df = final_df.loc[:, col_mask]

    return final_df


if __name__ == "__main__":
    import doctest

    doctest.testmod()
