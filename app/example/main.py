from typing import List, Tuple, Match, Counter
import re

def ordinamentoList(numeri):
    for i in range(len(numeri) - 1):
        for j in range(i + 1, len(numeri)):
            if numeri[i] > numeri[j]:
                numeri[i], numeri[j] = numeri[j], numeri[i]
    return numeri

def max(numeri):
    max_value = numeri[0]
    for num in numeri:
        if num > max_value:
            max_value = num   
    return max_value

def contaOccorrenze(list, element):
    count = 0
    for i in list:
        if i == element:
            count += 1
    return count    

def palindroma(stringa):
    return stringa == stringa[::-1]

def inverti_stringa(s):
    return s[::-1]

def reverse_words_preserve(text: str) -> str:
    def rev(m: Match) -> str:
        word = m.group(0)
        return word[::-1]
    
    # Cattura sequenze di lettere Unicode
    return re.sub(r"\w+", rev, text)

def sommaPari(numeri) -> int:
    return sum(num for num in numeri if num % 2 == 0)

def top_k_frequent_chars(s: str, k: int) -> List[Tuple[str, int]]:
    freq = Counter(s)	
    return freq.most_common(k)


import random
from typing import List

def quickselect(nums: List[int], k: int) -> int:
    """
    Restituisce il k-esimo elemento più grande in nums (1-based).
    """
    if not 1 <= k <= len(nums):
        raise ValueError("k fuori dall'intervallo")

    def select(left: int, right: int, k_smallest: int) -> int:
        pivot = nums[random.randint(left, right)]
        # partizionamento in-place
        low, high = left, right
        i = left
        while i <= high:
            if nums[i] < pivot:
                nums[low], nums[i] = nums[i], nums[low]
                low += 1; i += 1
            elif nums[i] > pivot:
                nums[i], nums[high] = nums[high], nums[i]
                high -= 1
            else:
                i += 1
        # low..high sono pivot
        if k_smallest < low:
            return select(left, low - 1, k_smallest)
        elif k_smallest > high:
            return select(high + 1, right, k_smallest)
        else:
            return nums[low]

    # k-esimo più grande = (n-k)-esimo più piccolo in 0-based
    return select(0, len(nums) - 1, len(nums) - k)

# Esempio
arr = [3,2,1,5,6,4]
print(quickselect(arr, 2))  # → 5




def test():
    numeri = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]  # Lista di input
    assert ordinamentoList(numeri) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "Test failed!"
    print("Test order passed!")
    assert inverti_stringa("Ciao") == "oaiC", "Test failed!"
    print("Test inverti_stringa passed!")
    assert contaOccorrenze("alessio", "s") == 2, "Test failed!"
    print("Test contaOccorrenze passed!")
    assert max(numeri) == 10, "Test failed!"
    print("Test max passed!")
    assert palindroma("ala"), "Test failed!"
    print("Test palindroma passed!")
    assert sommaPari(numeri) == 30, "Test failed!"
    print("Test sommaPari passed!")
    assert reverse_words_preserve("Ciao, mondo! Come va?") == "oaiC, odnom! emoC av?", "Test failed!"
    print("Test reverse_words_preserve passed!")
    assert top_k_frequent_chars("abracadabra!!!", 3) == [('a', 5), ('!', 3), ('b', 2)], "Test failed!"
    print("Test top_k_frequent_chars passed!")

if __name__ == "__main__":
    test()